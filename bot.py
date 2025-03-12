import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import datetime
import asyncio
from typing import Optional
import datetime
from zoneinfo import ZoneInfo
from globals import TOKEN, GUILD_ID, TARGET_MEMBER_ID, TARGET_USER_ID, DATA_FILE, ALLOWED_ROLES, STOCK_FILE, STOCK_HISTORY_FILE, UPDATE_INTERVAL_MINUTES, LOTTERY_FILE, AFK_CHANNEL_ID
from stocks import load_stocks
from utils import save_data, load_data

#keys are user IDs (as strings), values are dicts with session data. tracks active VCs
active_vc_sessions = {}

#sset up intents
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
with open("config.json", "r") as f:
    config = json.load(f)

current_market_event = None

bot = commands.Bot(command_prefix="!", intents=intents)

#constants for cards:
HEARTS   = chr(9829)  # ♥
DIAMONDS = chr(9830)  # ♦
SPADES   = chr(9824)  # ♠
CLUBS    = chr(9827)  # ♣
BACKSIDE = "backside"

def update_active_vc_sessions_on_startup():
    now = datetime.datetime.now()
    guild = bot.get_guild(GUILD_ID)
    if guild:
        for channel in guild.voice_channels:
            for member in channel.members:
                if not member.bot:
                    uid = str(member.id)
                    if uid not in active_vc_sessions:
                        non_bots = [m for m in channel.members if not m.bot]
                        active_vc_sessions[uid] = {
                            "join_time": now,
                            "channel_id": channel.id,
                            "last_alone_update": now if len(non_bots) == 1 else None,
                            "alone_accumulated": datetime.timedelta(0),
                            "afk": (channel.id == AFK_CHANNEL_ID)
                        }
                        print(f"Added {member.display_name} (ID: {uid}) to active VC sessions.")

# --- Helper Functions for Blackjack ---
def get_deck():
    deck = []
    for suit in (HEARTS, DIAMONDS, SPADES, CLUBS):
        for rank in map(str, range(2, 11)):
            deck.append((rank, suit))
        for rank in ('J', 'Q', 'K', 'A'):
            deck.append((rank, suit))
    random.shuffle(deck)
    return deck

def get_hand_value(cards):
    value = 0
    number_of_aces = 0
    for card in cards:
        rank = card[0]
        if rank == 'A':
            number_of_aces += 1
        elif rank in ('K', 'Q', 'J'):
            value += 10
        else:
            value += int(rank)
    #count aces as 1, then add 10 if it won't bust
    value += number_of_aces
    for _ in range(number_of_aces):
        if value + 10 <= 21:
            value += 10
    return value

def card_to_str(card):
    if card == BACKSIDE:
        return "??"
    return f"{card[0]}{card[1]}"

def hand_to_str(hand):
    return ", ".join(card_to_str(card) for card in hand)

def render_game_state(game, final=False):
    """Return a string representing the current state of the game."""
    if final:
        dealer_display = hand_to_str(game.dealer_hand)
    else:
        #hide the dealer's first card
        dealer_display = "??"
        if len(game.dealer_hand) > 1:
            dealer_display += ", " + ", ".join(card_to_str(card) for card in game.dealer_hand[1:])
    player_display = hand_to_str(game.player_hand)
    text = (f"**Dealer's Hand:** {dealer_display}\n"
            f"**Your Hand:** {player_display} (Value: {get_hand_value(game.player_hand)})\n"
            f"**Bet:** {game.bet} Beaned Bucks")
    return text


# --- Game State Class ---
class BlackjackGame:
    def __init__(self, player: discord.Member, bet: float):
        self.player = player
        self.bet = bet
        self.deck = get_deck()
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.finished = False
        self.result = None  # "win", "lose", or "tie"

# --- Interactive View ---
class BlackjackView(discord.ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=60)
        self.game = game

    async def end_game(self, interaction: discord.Interaction):
        if self.game.finished:
            return
        self.game.finished = True

        #dealer's turn hit until the dealer's hand value is at least 17.
        while get_hand_value(self.game.dealer_hand) < 17:
            self.game.dealer_hand.append(self.game.deck.pop())
            await asyncio.sleep(1)

        player_val = get_hand_value(self.game.player_hand)
        dealer_val = get_hand_value(self.game.dealer_hand)
        if player_val > 21:
            self.game.result = "lose"
        elif dealer_val > 21 or player_val > dealer_val:
            self.game.result = "win"
        elif player_val < dealer_val:
            self.game.result = "lose"
        else:
            self.game.result = "tie"

        for child in self.children:
            child.disabled = True

        outcome_text = ""
        if self.game.result == "win":
            outcome_text = f"You win {self.game.bet} Beaned Bucks!"
        elif self.game.result == "lose":
            outcome_text = f"You lose {self.game.bet} Beaned Bucks!"
        elif self.game.result == "tie":
            outcome_text = "It's a tie! Your bet is returned."

        content = render_game_state(self.game, final=True) + "\n\n" + outcome_text
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(content=content, view=self)
            else:
                await interaction.message.edit(content=content, view=self)
        except discord.NotFound:
            print("Message not found when trying to edit.")
        self.stop()

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.player:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return
        if self.game.finished:
            await interaction.response.defer()
            return

        self.game.player_hand.append(self.game.deck.pop())
        current_value = get_hand_value(self.game.player_hand)
        print(f"[Blackjack] Hit pressed. New hand: {self.game.player_hand} Value: {current_value}")

        if current_value > 21:
            await self.end_game(interaction)
        else:
            content = render_game_state(self.game)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(content=content, view=self)
                else:
                    await interaction.message.edit(content=content, view=self)
            except discord.NotFound:
                print("Message not found when trying to edit on Hit.")

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.player:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return
        await self.end_game(interaction)

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.success)
    async def double_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.player:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return
        if self.game.finished:
            await interaction.response.defer()
            return
        #doubling is allowed only if the player has exactly two cards.
        if len(self.game.player_hand) != 2:
            await interaction.response.send_message("You can only double down on your first move (with exactly 2 cards).", ephemeral=True)
            return

        #check if the player has enough funds to double down.
        #the additional cost is equal to the current bet.
        if not hasattr(self.game, 'remaining'):
            await interaction.response.send_message("Funds information missing.", ephemeral=True)
            return
        if self.game.remaining < self.game.bet:
            await interaction.response.send_message("You don't have enough funds to double down.", ephemeral=True)
            return

        #deduct additional funds and double the bet.
        self.game.remaining -= self.game.bet
        self.game.bet *= 2
        print(f"[Blackjack] Doubling down. New bet: {self.game.bet}. Remaining funds: {self.game.remaining}")
        #deal one card and automatically end the player's turn.
        self.game.player_hand.append(self.game.deck.pop())
        await self.end_game(interaction)


#in your blackjack command, after validating the bet:
def is_blackjack(hand):
    """Return True if hand is a blackjack (exactly 2 cards with value 21)."""
    return len(hand) == 2 and get_hand_value(hand) == 21
@bot.tree.command(
    name="blackjack",
    description="Play a round of Blackjack using your Beaned Bucks.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(bet="The amount of Beaned Bucks you want to bet (can be non-integer)")
async def blackjack(interaction: discord.Interaction, bet: str):
    print(f"[Blackjack] Invoked by {interaction.user} with bet {bet}")
    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0})
    balance = float(user_record.get("balance", 0))

    if bet.lower() == "all":
        bet = balance
    else:
        try:
            bet = float(bet)
        except ValueError:
            await interaction.response.send_message("Invalid bet amount.", ephemeral=True)
            return
        
    if bet <= 0:
        await interaction.response.send_message("Bet must be greater than 0.", ephemeral=True)
        return
    if bet > balance:
        await interaction.response.send_message("You don't have enough Beaned Bucks to make that bet.", ephemeral=True)
        return

    # Create a new blackjack game.
    game = BlackjackGame(interaction.user, bet)
    # Store starting balance and remaining funds (as floats).
    game.start_balance = balance
    game.remaining = balance - bet

    # Check for blackjack immediately (a two-card 21).
    if is_blackjack(game.player_hand):
        if is_blackjack(game.dealer_hand):
            game.result = "tie"
        else:
            game.result = "win"
            # Apply 1.5x multiplier for blackjack; keep it as a float.
            game.bet = game.bet * 1.5
        content = render_game_state(game, final=True)
        if game.result == "win":
            outcome_text = f"Blackjack! You win {game.bet} Beaned Bucks!"
        else:
            outcome_text = "Both you and the dealer got blackjack. It's a tie!"
        content += "\n\n" + outcome_text
        await interaction.response.send_message(content=content, ephemeral=False)
        
        # Update the balance.
        if game.result == "win":
            user_record["balance"] = balance + game.bet
            print(f"[Blackjack] User wins with blackjack. New balance should be {balance + game.bet}.")
        else:
            user_record["balance"] = balance  # tie, no change
            print(f"[Blackjack] Game tied with blackjack. Balance remains {balance}.")
        data[user_id] = user_record
        save_data(data)
        try:
            await interaction.followup.send(f"Your new balance is {user_record['balance']} Beaned Bucks.", ephemeral=False)
        except Exception as e:
            print(f"[Blackjack] Error sending followup: {e}")
        return

    # If no immediate blackjack, proceed with the interactive view.
    content = render_game_state(game)
    view = BlackjackView(game)
    await interaction.response.send_message(content=content, view=view, ephemeral=False)
    await view.wait()

    # Update the player's balance using the updated game.bet (float arithmetic).
    if game.result == "win":
        user_record["balance"] = balance + game.bet
        print(f"[Blackjack] User wins. New balance should be {balance + game.bet}.")
    elif game.result == "lose":
        user_record["balance"] = balance - game.bet
        print(f"[Blackjack] User loses. New balance should be {balance - game.bet}.")
    elif game.result == "tie":
        print("[Blackjack] Game tied. Balance remains unchanged.")
        user_record["balance"] = balance
    else:
        print("[Blackjack] Game result not set. No balance change.")

    data[user_id] = user_record
    save_data(data)
    print(f"[Blackjack] User record after game: {user_record}")

    try:
        await interaction.followup.send(f"Your new balance is {user_record['balance']} Beaned Bucks.", ephemeral=False)
    except Exception as e:
        print(f"[Blackjack] Error sending followup message: {e}")

  
# --- Voice State Update Event ---
@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.datetime.now()
    uid = str(member.id)

    def non_bot_members(channel):
        return [m for m in channel.members if not m.bot]

    # -- Notification for target user --
    if member.id == TARGET_USER_ID:
        if before.channel is None and after.channel is not None:
            notif_channel = discord.utils.get(member.guild.text_channels, name="notif")
            if notif_channel is None:
                print("Channel #notif not found.")
            else:
                role = discord.utils.get(member.guild.roles, name="notif")
                if role is None:
                    print("Role 'notif' not found.")
                else:
                    await notif_channel.send(f"{role.mention} Alert: {member.mention} has joined a voice channel!")

    #determine if the channel is the AFK channel.
    def is_afk(channel):
        return channel and channel.id == AFK_CHANNEL_ID

    #if a user joins a voice channel:
    if before.channel is None and after.channel is not None:
        channel = after.channel
        members = non_bot_members(channel)
        alone = (len(members) == 1)
        #mark session as AFK if channel is the AFK channel.
        active_vc_sessions[uid] = {
            "join_time": now,
            "channel_id": channel.id,
            "last_alone_update": now if alone else None,
            "alone_accumulated": datetime.timedelta(0),
            "afk": is_afk(channel)
        }
    #if a user leaves a voice channel:
    elif before.channel is not None and after.channel is None:
        session = active_vc_sessions.pop(uid, None)
        if session:
            session_duration = now - session["join_time"]
            alone_time = session["alone_accumulated"]
            if session["last_alone_update"]:
                alone_time += now - session["last_alone_update"]
            data = load_data()
            #if session was AFK, update "vc_afk"; else update normal VC times.
            if session.get("afk"):
                record = data.get(uid, {"vc_afk": 0})
                record["vc_afk"] = record.get("vc_afk", 0) + session_duration.total_seconds()
            else:
                record = data.get(uid, {"vc_time": 0, "vc_timealone": 0})
                record["vc_time"] = record.get("vc_time", 0) + session_duration.total_seconds()
                record["vc_timealone"] = record.get("vc_timealone", 0) + alone_time.total_seconds()
            data[uid] = record
            save_data(data)
    #if a user switches voice channels:
    elif before.channel is not None and after.channel is not None:
        #end the old session.
        session = active_vc_sessions.pop(uid, None)
        if session:
            session_duration = now - session["join_time"]
            alone_time = session["alone_accumulated"]
            if session["last_alone_update"]:
                alone_time += now - session["last_alone_update"]
            data = load_data()
            #update the appropriate field based on whether it was AFK.
            if session.get("afk"):
                record = data.get(uid, {"vc_afk": 0})
                record["vc_afk"] = record.get("vc_afk", 0) + session_duration.total_seconds()
            else:
                record = data.get(uid, {"vc_time": 0, "vc_timealone": 0})
                record["vc_time"] = record.get("vc_time", 0) + session_duration.total_seconds()
                record["vc_timealone"] = record.get("vc_timealone", 0) + alone_time.total_seconds()
            data[uid] = record
            save_data(data)
        #start a new session for the new channel.
        channel = after.channel
        members = non_bot_members(channel)
        alone = (len(members) == 1)
        active_vc_sessions[uid] = {
            "join_time": now,
            "channel_id": channel.id,
            "last_alone_update": now if alone else None,
            "alone_accumulated": datetime.timedelta(0),
            "afk": is_afk(channel)
        }

    #additionally update alone status for users in both the before and after channels.
    for channel in [before.channel, after.channel]:
        if channel is None:
            continue
        members = non_bot_members(channel)
        for m in members:
            s = active_vc_sessions.get(str(m.id))
            if s and s["channel_id"] == channel.id:
                if len(members) == 1:
                    if s["last_alone_update"] is None:
                        s["last_alone_update"] = now
                else:
                    if s["last_alone_update"]:
                        delta = now - s["last_alone_update"]
                        s["alone_accumulated"] += delta
                        s["last_alone_update"] = None

# --- Join/Leave Notification Commands ---
@bot.tree.command(name="joinnotification", description="Join the notif notifications", guild=discord.Object(id=GUILD_ID))
async def joinnotification(interaction: discord.Interaction):
    role = discord.utils.get(interaction.guild.roles, name="notif")
    if role is None:
        await interaction.response.send_message("The role 'notif' does not exist.", ephemeral=True)
        return
    member = interaction.user
    if role in member.roles:
        await interaction.response.send_message("You already have the 'notif' role.", ephemeral=True)
    else:
        try:
            await member.add_roles(role)
            await interaction.response.send_message("You have been given the 'notif' role.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Error assigning the role.", ephemeral=True)

@bot.tree.command(name="leavenotification", description="Leave the notif notifications", guild=discord.Object(id=GUILD_ID))
async def leavenotification(interaction: discord.Interaction):
    role = discord.utils.get(interaction.guild.roles, name="notif")
    if role is None:
        await interaction.response.send_message("The role 'notif' does not exist.", ephemeral=True)
        return
    member = interaction.user
    if role not in member.roles:
        await interaction.response.send_message("You don't have the 'notif' role.", ephemeral=True)
    else:
        try:
            await member.remove_roles(role)
            await interaction.response.send_message("The 'notif' role has been removed.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Error removing the role.", ephemeral=True)
@bot.tree.command(
    name="roulette",
    description="Play roulette. Bet on a number or category (odd, even, red, black, 1st12, 2nd12, 3rd12).",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    bet="The amount of Beaned Bucks to bet",
    choice="Your bet: a number (0-36) or one of: odd, even, red, black, 1st12, 2nd12, 3rd12"
)
async def roulette(interaction: discord.Interaction, bet: str, choice: str):
    #validate bet amount.
    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0})
    current_balance = float(user_record.get("balance", 0))
    if bet.lower() == "all":
        bet = current_balance
    else:
        try:
            bet = float(bet)
        except ValueError:
            await interaction.response.send_message("Invalid bet amount.", ephemeral=True)
            return
        
    if bet <= 0:
        await interaction.response.send_message("Bet must be greater than 0.", ephemeral=True)
        return
    if bet > current_balance:
        await interaction.response.send_message("You do not have enough Beaned Bucks for that bet.", ephemeral=True)
        return

    #deduct the wager from the user's balance immediately.
    user_record["balance"] = current_balance - bet
    data[user_id] = user_record
    save_data(data)

    #simulate the roulette spin (0-36)
    outcome = random.randint(0, 36)

    #define red and black numbers (using typical European roulette colors)
    red_numbers = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    black_numbers = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

    #determine the payout multiplier.
    multiplier = 0  #if remains 0, the bet loses
    win = False
    choice_lower = choice.lower()

    #if the choice is a digit (i.e. betting on a specific number):
    if choice.isdigit():
        chosen_number = int(choice)
        if 0 <= chosen_number <= 36:
            if chosen_number == outcome:
                multiplier = 35
                win = True
        else:
            await interaction.response.send_message("Number must be between 0 and 36.", ephemeral=True)
            return
    elif choice_lower == "odd":
        if outcome != 0 and outcome % 2 == 1:
            multiplier = 1
            win = True
    elif choice_lower == "even":
        if outcome != 0 and outcome % 2 == 0:
            multiplier = 1
            win = True
    elif choice_lower == "red":
        if outcome in red_numbers:
            multiplier = 1
            win = True
    elif choice_lower == "black":
        if outcome in black_numbers:
            multiplier = 1
            win = True
    elif choice_lower in ["1st12", "first12"]:
        if 1 <= outcome <= 12:
            multiplier = 2
            win = True
    elif choice_lower in ["2nd12", "second12"]:
        if 13 <= outcome <= 24:
            multiplier = 2
            win = True
    elif choice_lower in ["3rd12", "third12"]:
        if 25 <= outcome <= 36:
            multiplier = 2
            win = True
    else:
        await interaction.response.send_message("Invalid bet choice. Please choose a number (0-36) or one of: odd, even, red, black, 1st12, 2nd12, 3rd12.", ephemeral=True)
        return

    #create an embed to display the result.
    embed = discord.Embed(
        title="Roulette Result",
        color=discord.Color.purple(),
        timestamp=datetime.datetime.utcnow()
    )
    embed.add_field(name="Outcome", value=str(outcome), inline=True)
    embed.add_field(name="Your Bet", value=choice, inline=True)
    embed.add_field(name="Wager", value=str(bet), inline=True)

    if win:
        #if winning, payout is wager returned plus winnings:
        winnings = bet * multiplier  #profit
        total_return = bet + winnings  #total returned
        embed.add_field(name="Result", value=f"WIN! Multiplier: {multiplier}x\nWinnings: {winnings} Beaned Bucks\nTotal Return: {total_return}", inline=False)
        #add the winnings back to user's balance.
        user_record["balance"] += total_return
    else:
        embed.add_field(name="Result", value="LOSE!", inline=False)
    data[user_id] = user_record
    save_data(data)

    embed.set_footer(text=f"New Balance: {user_record['balance']} Beaned Bucks")
    await interaction.response.send_message(embed=embed)

#leaderboard command
@bot.tree.command(
    name="leaderboard",
    description="View the leaderboard. Categories: networth, time, timealone, or timeafk.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(category="Choose a category: networth, time, timealone, or timeafk")
async def leaderboard(interaction: discord.Interaction, category: str):
    category = category.lower()
    data = load_data()
    leaderboard_list = []

    if category == "networth":
        stock_prices = load_stocks()
        for user_id, record in data.items():
            balance = record.get("balance", 0)
            portfolio = record.get("portfolio", {})
            portfolio_value = sum(stock_prices.get(stock, 0) * shares for stock, shares in portfolio.items())
            networth = balance + portfolio_value
            leaderboard_list.append((user_id, networth))
        leaderboard_list.sort(key=lambda x: x[1], reverse=True)
        title = "Net Worth Leaderboard"
    elif category == "time":
        for user_id, record in data.items():
            vc_time = record.get("vc_time", 0)
            leaderboard_list.append((user_id, vc_time))
        leaderboard_list.sort(key=lambda x: x[1], reverse=True)
        title = "Voice Channel Time Leaderboard"
    elif category == "timealone":
        for user_id, record in data.items():
            vc_timealone = record.get("vc_timealone", 0)
            leaderboard_list.append((user_id, vc_timealone))
        leaderboard_list.sort(key=lambda x: x[1], reverse=True)
        title = "Voice Channel Alone Time Leaderboard"
    elif category == "timeafk":
        for user_id, record in data.items():
            vc_afk = record.get("vc_afk", 0)
            leaderboard_list.append((user_id, vc_afk))
        leaderboard_list.sort(key=lambda x: x[1], reverse=True)
        title = "AFK Time Leaderboard"
    else:
        await interaction.response.send_message("Invalid category. Please choose networth, time, timealone, or timeafk.", ephemeral=True)
        return

    embed = discord.Embed(title=title, color=discord.Color.gold())
    count = 0
    for user_id, value in leaderboard_list[:10]:
        count += 1
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        if category == "networth":
            display_value = f"{value:.2f} Beaned Bucks"
        else:
            hrs = value // 3600
            mins = (value % 3600) // 60
            secs = value % 60
            display_value = f"{int(hrs)}h {int(mins)}m {int(secs)}s"
        embed.add_field(name=f"{count}. {name}", value=display_value, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="exit",
    description="Shut down the bot and update VC trackers. (Restricted to users with the 'him' role.)",
    guild=discord.Object(id=GUILD_ID)
)
async def exit(interaction: discord.Interaction):
    #check if the invoking user has the "him" role (case-insensitive).
    if not any(role.name.lower() == "him" for role in interaction.user.roles):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    now = datetime.datetime.now()
    data = load_data()
    #process all active VC sessions.
    for uid, session in list(active_vc_sessions.items()):
        session_duration = now - session["join_time"]
        alone_time = session["alone_accumulated"]
        if session["last_alone_update"]:
            alone_time += now - session["last_alone_update"]
        record = data.get(uid, {"vc_time": 0, "vc_timealone": 0})
        record["vc_time"] = record.get("vc_time", 0) + session_duration.total_seconds()
        record["vc_timealone"] = record.get("vc_timealone", 0) + alone_time.total_seconds()
        data[uid] = record
        #remove this session from the active sessions.
        del active_vc_sessions[uid]
    save_data(data)
    await interaction.response.send_message("Shutting down the bot and updating VC trackers...", ephemeral=True)
    await bot.close()

# --- Lottery Functions ---

def load_lottery():
    try:
        with open(LOTTERY_FILE, "r") as f:
            data = json.load(f)
            #ensure necessary keys exist cause this broke everything
            if "Jackpot" not in data:
                data["Jackpot"] = 100000
            if "Tickets" not in data:
                data["Tickets"] = []
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        default_data = {"Jackpot": 100000, "Tickets": []}
        save_lottery(default_data)
        return default_data

def save_lottery(data):
    with open(LOTTERY_FILE, "w") as f:
        json.dump(data, f, indent=4)

def lottery_draw():
    lottery_data = load_lottery()
    jackpot = lottery_data.get("Jackpot", 100000)
    tickets = lottery_data.get("Tickets", [])
    #draw 5 unique numbers from 1 to 60.
    drawn_numbers = random.sample(range(1, 61), 5)
    drawn_set = set(drawn_numbers)
    print(f"[Lottery] Drawn Numbers: {drawn_numbers}")

    #for each ticket count how many numbers match and assign a raw multiplier
    #mapping: 1 match = 0.20, 2 matches = 0.40, 3 matches = 0.60, 4 matches = 0.80, 5 matches = 1.00.
    for ticket in tickets:
        chosen = set(ticket.get("numbers", []))
        if len(chosen) != 5:
            ticket["raw_multiplier"] = 0
            continue
        matches = len(chosen.intersection(drawn_set))
        if matches == 1:
            ticket["raw_multiplier"] = 0.20
        elif matches == 2:
            ticket["raw_multiplier"] = 0.40
        elif matches == 3:
            ticket["raw_multiplier"] = 0.60
        elif matches == 4:
            ticket["raw_multiplier"] = 0.80
        elif matches == 5:
            ticket["raw_multiplier"] = 1.00
        else:
            ticket["raw_multiplier"] = 0

    #filter winning tickets (raw_multiplier > 0) and sum their multipliers. (nerd stuff)
    winning_tickets = [t for t in tickets if t["raw_multiplier"] > 0]
    total_raw = sum(t["raw_multiplier"] for t in winning_tickets)

    payouts = {}
    if total_raw > 0:
        for ticket in winning_tickets:
            payout_fraction = ticket["raw_multiplier"] / total_raw
            payout = jackpot * payout_fraction
            uid = ticket["user_id"]
            payouts[uid] = payouts.get(uid, 0) + payout

    total_payout = sum(payouts.values())
    new_jackpot = jackpot - total_payout + 25000

    lottery_data["Jackpot"] = new_jackpot
    lottery_data["Tickets"] = []
    save_lottery(lottery_data)

    return drawn_numbers, payouts  

@bot.tree.command(
    name="lotteryticket",
    description="Buy a lottery ticket for 5,000 Beaned Bucks. Choose 5 unique numbers from 1 to 60.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    numbers="Enter 5 unique numbers between 1 and 60 separated by spaces (e.g., '5 12 23 34 45')"
)
async def lotteryticket(interaction: discord.Interaction, numbers: str):
    try:
        chosen_numbers = [int(n) for n in numbers.split()]
    except ValueError:
        await interaction.response.send_message("Invalid numbers. Please enter 5 numbers separated by spaces.", ephemeral=True)
        return

    if len(chosen_numbers) != 5 or len(set(chosen_numbers)) != 5 or any(n < 1 or n > 60 for n in chosen_numbers):
        await interaction.response.send_message("You must provide 5 unique numbers between 1 and 60.", ephemeral=True)
        return

    #deduct ticket price from user's balance.
    user_data = load_data()
    user_id = str(interaction.user.id)
    user_record = user_data.get(user_id, {"balance": 0})
    if user_record.get("balance", 0) < 5000:
        await interaction.response.send_message("You do not have enough Beaned Bucks to buy a lottery ticket.", ephemeral=True)
        return

    user_record["balance"] -= 5000
    user_data[user_id] = user_record
    save_data(user_data)

    #update the lottery jackpot by adding 5,000.
    lottery_data = load_lottery()
    lottery_data["Jackpot"] = lottery_data.get("Jackpot", 100000) + 5000
    #add the ticket to the lottery.
    ticket = {"user_id": user_id, "numbers": sorted(chosen_numbers)}
    lottery_data["Tickets"].append(ticket)
    save_lottery(lottery_data)

    await interaction.response.send_message(f"Ticket purchased with numbers: {sorted(chosen_numbers)}. 5000 Beaned Bucks deducted.", ephemeral=False)

@bot.tree.command(
    name="lotterytotal",
    description="View the current lottery jackpot.",
    guild=discord.Object(id=GUILD_ID)
)
async def lotterytotal(interaction: discord.Interaction):
    lottery_data = load_lottery()
    jackpot = lottery_data.get("Jackpot", 100000)
    await interaction.response.send_message(f"The current lottery jackpot is {jackpot} Beaned Bucks.", ephemeral=False)
@bot.tree.command(
    name="lotterydraw",
    description="Perform the lottery draw. (Restricted to lottery admins.)",
    guild=discord.Object(id=GUILD_ID)
)

async def lotterydraw(interaction: discord.Interaction):
    #check permission
    if not any(role.name.lower() == ALLOWED_ROLES for role in interaction.user.roles):
        await interaction.response.send_message("You do not have permission to run the lottery draw.", ephemeral=True)
        return

    drawn_numbers, payouts = lottery_draw()
    #update winners Beaned Bucks in user data
    user_data = load_data()
    winners_msg = ""
    if payouts:
        for uid, amount in payouts.items():
            record = user_data.get(uid, {"balance": 0})
            record["balance"] = record.get("balance", 0) + amount
            user_data[uid] = record
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            winners_msg += f"{name} wins {amount:.2f} Beaned Bucks.\n"
        save_data(user_data)
    else:
        winners_msg = "No winning tickets this draw."

    await interaction.response.send_message(f"Drawn Numbers: {drawn_numbers}\n{winners_msg}")

@tasks.loop(hours=24)
async def daily_lottery_draw():
    #calculate delay until next 4pm Eastern
    now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
    target_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et >= target_et:
        target_et += datetime.timedelta(days=1)
    delay = (target_et - now_et).total_seconds()
    print(f"[Lottery] Waiting {delay} seconds until daily lottery draw.")
    await asyncio.sleep(delay)

    drawn_numbers, payouts = lottery_draw()
    #update winners Beaned Bucks.
    user_data = load_data()
    winners_msg = ""
    if payouts:
        for uid, amount in payouts.items():
            record = user_data.get(uid, {"balance": 0})
            record["balance"] = record.get("balance", 0) + amount
            user_data[uid] = record
            member = bot.get_guild(GUILD_ID).get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            winners_msg += f"{name} wins {amount:.2f} Beaned Bucks.\n"
        save_data(user_data)
    else:
        winners_msg = "No winning tickets this draw."

    #post the results to a specific channel 
    channel = discord.utils.get(bot.get_all_channels(), name="bot-output")
    if channel:
        await channel.send(f"Daily Lottery Draw at 4pm ET:\nDrawn Numbers: {drawn_numbers}\n{winners_msg}")
    else:
        print("Channel not found for lottery.")

@daily_lottery_draw.before_loop
async def before_daily_lottery_draw():
    now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
    #set the target time to today at 4pm ET
    target_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    #if its already past 4pm, set the target to tomorrow
    if now_et >= target_et:
        target_et += datetime.timedelta(days=1)
    #calculate delay until the next 4pm ET
    delay = (target_et - now_et).total_seconds()
    print(f"Waiting {delay} seconds until next 4pm ET.")
    await asyncio.sleep(delay)

#onready event
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.load_extension("general")
    await bot.load_extension("help")
    await bot.load_extension("stocks")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    update_active_vc_sessions_on_startup()
    daily_lottery_draw.start()

bot.run(TOKEN)
