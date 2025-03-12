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

def load_stocks():
    try:
        with open(STOCK_FILE, "r") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Stocks data is not a dictionary.")
            return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        default_data = {
            "INK": 300.0,
            "BEANEDCOIN": 10.0
        }
        save_stocks(default_data)
        return default_data
    
def save_stocks(data):
    with open(STOCK_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_stock_history():
    try:
        with open(STOCK_HISTORY_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_stock_history(history):
    with open(STOCK_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def choose_new_market_event():
    events = [
        ("none", 0.90),
        ("rally", 0.05),
        ("crash", 0.05)
    ]
    total_weight = sum(weight for event, weight in events)
    r = random.random() * total_weight
    cumulative = 0
    for event, weight in events:
        cumulative += weight
        if r < cumulative:
            if event == "none":
                return None
            else:
                #for chosen events, set a random duration
                duration = random.randint(1, 3)
                return {"event": event, "duration": duration}
    return None
def update_stock_prices():
    global current_market_event
    data = load_stocks()
    history = load_stock_history()
    now_iso = datetime.datetime.now().isoformat()
    changes = {}

    #if no persistent event is active, always try to choose one.
    if current_market_event is None:
        current_market_event = choose_new_market_event()
        if current_market_event:
            print(f"[Market Event] New event started: {current_market_event}")
        else:
            print("[Market Event] No event this update.")

    event_type = current_market_event["event"] if current_market_event else None

    for stock, price in data.items():
        old_price = price

        if event_type == "rally":
            if random.random() < 0.70:
                change_percent = random.uniform(0.10, 0.20)
                new_price = price * (1 + change_percent)
            else:
                change_percent = random.uniform(0.005, 0.05)
                if random.random() < 0.5:
                    change_percent = -change_percent
                new_price = price * (1 + change_percent)
        elif event_type == "crash":
            if random.random() < 0.70:
                change_percent = random.uniform(0.10, 0.20)
                new_price = price * (1 - change_percent)
            else:
                change_percent = random.uniform(0.005, 0.05)
                if random.random() < 0.5:
                    change_percent = -change_percent
                new_price = price * (1 + change_percent)
        else:
            #normal update.
            if random.random() < 0.01:
                jump_factor = random.uniform(0.5, 0.95)
                if random.random() < 0.5:
                    new_price = price * (1 + jump_factor)
                else:
                    new_price = price * (1 - jump_factor)
            else:
                change_percent = random.uniform(0.005, 0.05)
                if random.random() < 0.5:
                    change_percent = -change_percent
                new_price = price * (1 + change_percent)

        new_price = max(round(new_price, 2), 0.01)
        data[stock] = new_price

        absolute_change = round(new_price - old_price, 2)
        percent_change = round(((new_price - old_price) / old_price) * 100, 2) if old_price != 0 else 0
        changes[stock] = {"old": old_price, "new": new_price, "abs": absolute_change, "perc": percent_change}

        if stock not in history:
            history[stock] = []
        history[stock].append({"timestamp": now_iso, "price": new_price})

    #decrease event duration if an event is active.
    if current_market_event:
        current_market_event["duration"] -= 1
        if current_market_event["duration"] <= 0:
            print(f"[Market Event] Event ended: {current_market_event}")
            current_market_event = None

    save_stocks(data)
    save_stock_history(history)
    print("Stock prices updated:", data)
    return changes


@bot.tree.command(
    name="stockbuy",
    description="Invest a specified amount of Beaned Bucks to buy shares. Use 'all' to invest your entire balance.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    stock="The stock symbol to buy (e.g. ACME)",
    amount="The amount of Beaned Bucks you want to invest (or 'all')"
)
async def buy(interaction: discord.Interaction, stock: str, amount: str):
    stocks_data = load_stocks()
    stock = stock.upper()
    if stock not in stocks_data:
        await interaction.response.send_message("Invalid stock symbol.", ephemeral=True)
        return

    price = stocks_data[stock]
    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0, "portfolio": {}, "total_spent": 0, "total_earned": 0})
    current_balance = float(user_record.get("balance", 0))

    #determine investment amount.
    if amount.lower() == "all":
        invest_amount = current_balance
    else:
        try:
            invest_amount = float(amount)
        except ValueError:
            await interaction.response.send_message("Invalid investment amount.", ephemeral=True)
            return

    if invest_amount <= 0:
        await interaction.response.send_message("Investment amount must be greater than 0.", ephemeral=True)
        return
    if invest_amount > current_balance:
        await interaction.response.send_message(f"You do not have enough Beaned Bucks to invest {invest_amount}.", ephemeral=True)
        return

    shares = invest_amount / price
    user_record["balance"] = current_balance - invest_amount
    portfolio = user_record.get("portfolio", {})
    portfolio[stock] = portfolio.get(stock, 0) + shares
    user_record["portfolio"] = portfolio
    user_record["total_spent"] = user_record.get("total_spent", 0) + invest_amount

    data[user_id] = user_record
    save_data(data)

    await interaction.response.send_message(
        f"Successfully invested {invest_amount} Beaned Bucks in {stock} at {price} per share.\n"
        f"You now own {portfolio[stock]} shares of {stock}.\n"
        f"Your new balance is {user_record['balance']} Beaned Bucks."
    )


@bot.tree.command(
    name="portfolio",
    description="View your stock holdings, and track your profit (spent vs earned).",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(user="Optional: The user whose portfolio you want to see (defaults to yourself)")
async def portfolio(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    data = load_data()
    user_id = str(target.id)
    user_record = data.get(user_id, {"balance": 0, "portfolio": {}, "total_spent": 0, "total_earned": 0})
    portfolio_holdings = user_record.get("portfolio", {})

    stock_prices = load_stocks()

    embed = discord.Embed(
        title=f"{target.display_name}'s Portfolio",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Balance: {user_record.get('balance', 0)} Beaned Bucks")
    
    if not portfolio_holdings:
        embed.description = "No stock holdings found."
    else:
        total_value = 0.0
        for symbol, shares in portfolio_holdings.items():
            price = stock_prices.get(symbol, 0)
            value = price * shares
            total_value += value
            embed.add_field(
                name=symbol,
                value=f"Shares: {shares}\nPrice: {price} Beaned Bucks\nValue: {round(value, 2)} Beaned Bucks",
                inline=True
            )
        embed.add_field(
            name="Total Holdings Value",
            value=f"{round(total_value, 2)} Beaned Bucks",
            inline=False
        )
    
    #add profit tracking
    total_spent = user_record.get("total_spent", 0)
    total_earned = user_record.get("total_earned", 0)
    net_profit = total_earned - total_spent
    embed.add_field(name="Total Invested", value=f"{total_spent} Beaned Bucks", inline=True)
    embed.add_field(name="Total Earned", value=f"{total_earned} Beaned Bucks", inline=True)
    embed.add_field(name="Net Profit", value=f"{net_profit} Beaned Bucks", inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(
    name="stocksell",
    description="Sell shares of a stock (fractional shares allowed) to receive Beaned Bucks.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    stock="The stock symbol you want to sell (e.g. ACME)",
    quantity="The number of shares you want to sell (can be fractional, e.g. 0.68, or type 'all' to sell everything)"
)
async def sell(interaction: discord.Interaction, stock: str, quantity: str):
    stock = stock.upper()

    #load current stock data.
    stocks_data = load_stocks()
    if stock not in stocks_data:
        await interaction.response.send_message("Invalid stock symbol.", ephemeral=True)
        return

    price = stocks_data[stock]

    #load user data.
    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0, "portfolio": {}, "total_spent": 0, "total_earned": 0})
    portfolio = user_record.get("portfolio", {})

    if stock not in portfolio:
        await interaction.response.send_message("You do not own any shares of that stock.", ephemeral=True)
        return

    #determine the quantity to sell.
    try:
        if quantity.lower() == "all":
            sell_quantity = portfolio[stock]
        else:
            sell_quantity = float(quantity)
    except Exception as e:
        await interaction.response.send_message("Invalid quantity format. Please provide a number or 'all'.", ephemeral=True)
        return

    if sell_quantity <= 0:
        await interaction.response.send_message("Quantity must be greater than zero.", ephemeral=True)
        return

    if portfolio[stock] < sell_quantity:
        await interaction.response.send_message("You do not own enough shares of that stock to sell.", ephemeral=True)
        return

    sale_value = round(price * sell_quantity, 2)

    #update portfolio.
    portfolio[stock] -= sell_quantity
    if portfolio[stock] <= 0:
        del portfolio[stock]
    user_record["portfolio"] = portfolio

    #update user's balance.
    user_record["balance"] += sale_value

    #update total earned.
    user_record["total_earned"] = user_record.get("total_earned", 0) + sale_value

    data[user_id] = user_record
    save_data(data)

    await interaction.response.send_message(
        f"Successfully sold {sell_quantity} shares of {stock} at {price} Beaned Bucks each for a total of {sale_value} Beaned Bucks.\n"
        f"Your new balance is {user_record['balance']} Beaned Bucks."
    )



def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

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

#background task that updates the stock market periodically.

@tasks.loop(minutes=UPDATE_INTERVAL_MINUTES)
async def stock_market_loop():
    changes = update_stock_prices()
    
    #create an embed for the stock update.
    embed = discord.Embed(
        title="Stock Market Update",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_footer(text="Prices update every 20 minute")
    
    #add a field for each stock.
    for stock, change in changes.items():
        sign = "+" if change["abs"] >= 0 else ""
        field_value = (
            f"**Old:** {change['old']}\n"
            f"**New:** {change['new']}\n"
            f"**Change:** {sign}{change['abs']} ({sign}{change['perc']}%)"
        )
        embed.add_field(name=stock, value=field_value, inline=True)
    
    #find the channel named "stocks" and send the embed.
    channel = discord.utils.get(bot.get_all_channels(), name="bot-output")
    if channel is not None:
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to send embed: {e}")
    else:
        print("Channel '#stocks' not found.")

@stock_market_loop.before_loop
async def before_stock_loop():
    await bot.wait_until_ready()

@bot.tree.command(
    name="stocks",
    description="View current stock prices, or view a specific stock's price history.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(stock="Optional: The stock symbol to view history for")
async def stocks(interaction: discord.Interaction, stock: Optional[str] = None):
    current_prices = load_stocks()
    
    #if no specific stock is provided, display current prices for all stocks.
    if stock is None:
        msg = "**Current Stock Prices:**\n"
        for sym, price in current_prices.items():
            msg += f"**{sym}**: {price} Beaned Bucks\n"
        await interaction.response.send_message(msg)
    else:
        stock = stock.upper()
        #check if the stock exists in current data.
        if stock not in current_prices:
            await interaction.response.send_message(f"Stock symbol '{stock}' not found.", ephemeral=True)
            return

        #retrieve current price.
        price = current_prices[stock]
        msg = f"**{stock}**\nCurrent Price: {price} Beaned Bucks\n\n"
        
        #load the stock history.
        history = load_stock_history()
        if stock in history and history[stock]:
            msg += "**Price History (last 10 updates):**\n"
            for record in history[stock][-10:]:
                timestamp = record["timestamp"]
                hist_price = record["price"]
                msg += f"{timestamp}: {hist_price}\n"
        else:
            msg += "No history available."
        
        await interaction.response.send_message(msg)


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
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    update_active_vc_sessions_on_startup()
    stock_market_loop.start()
    daily_lottery_draw.start()


bot.run(TOKEN)
