import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import datetime
import asyncio
from typing import Optional


# Set up intents (members and voice_states are required)
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
GUILD_ID = int(config["guild_id"])
TARGET_MEMBER_ID = int(config["target_member_id"])
# Replace with your actual guild/server ID
GUILD_ID = 569672255508840449  # Your guild/server ID
# The specific user ID to watch for
TARGET_USER_ID = 398607026176917535
DATA_FILE = "data.json"
ALLOWED_ROLES = ["him", "super admin"]
STOCK_FILE = "stocks.json"
STOCK_HISTORY_FILE = "stock_history.json"
UPDATE_INTERVAL_MINUTES = 20 #changes stock interval

bot = commands.Bot(command_prefix="!", intents=intents)

# Constants for cards:
HEARTS   = chr(9829)  # ♥
DIAMONDS = chr(9830)  # ♦
SPADES   = chr(9824)  # ♠
CLUBS    = chr(9827)  # ♣
BACKSIDE = "backside"

def load_stocks():
    try:
        with open(STOCK_FILE, "r") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Stocks data is not a dictionary.")
            return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        # Use default stock data if file not found or invalid.
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

def update_stock_prices():
    data = load_stocks()         # Loads a dictionary: { "TWINKS": 300.0, ... }
    history = load_stock_history()  # Loads the history (a dictionary mapping stock -> list of updates)
    now_iso = datetime.datetime.now().isoformat()
    changes = {}
    for stock, price in data.items():
        old_price = price
        if random.random() < 0.01:  # 1% chance for a big jump (50-95% change)
            jump_factor = random.uniform(0.5, 0.95)
            if random.random() < 0.5:
                new_price = price * (1 + jump_factor)
            else:
                new_price = price * (1 - jump_factor)
            print(f"[Stock Market] {stock} BIG jump: {old_price} -> {new_price}")
        else:
            # Regular update: Change price by a random percentage between 0.5% and 5%.
            change_percent = random.uniform(0.005, 0.05)
            if random.random() < 0.5:
                change_percent = -change_percent
            new_price = price * (1 + change_percent)
        new_price = max(round(new_price, 2), 0.01)
        data[stock] = new_price

        # Compute absolute and percentage change.
        absolute_change = round(new_price - old_price, 2)
        percent_change = round(((new_price - old_price) / old_price) * 100, 2) if old_price != 0 else 0
        changes[stock] = {"old": old_price, "new": new_price, "abs": absolute_change, "perc": percent_change}

        # Append the new price to history.
        if stock not in history:
            history[stock] = []
        history[stock].append({"timestamp": now_iso, "price": new_price})
    
    save_stocks(data)
    save_stock_history(history)
    print("Stock prices updated:", data)
    return changes


@bot.tree.command(
    name="buystock",
    description="Invest a specified amount of Beaned Bucks to buy shares (fractional shares allowed).",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    stock="The stock symbol to buy (e.g. ACME)",
    amount="The amount of Beaned Bucks you want to invest"
)
async def buy(interaction: discord.Interaction, stock: str, amount: float):
    if amount <= 0:
        await interaction.response.send_message("Investment amount must be greater than 0.", ephemeral=True)
        return

    # Load current stock data. (Stocks JSON is a simple dict.)
    stocks_data = load_stocks()  
    stock = stock.upper()
    if stock not in stocks_data:
        await interaction.response.send_message("Invalid stock symbol.", ephemeral=True)
        return

    price = stocks_data[stock]
    # Calculate fractional shares; do not round.
    shares = amount / price  

    # Load the user's data.
    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0, "portfolio": {}})
    current_balance = user_record.get("balance", 0)

    if current_balance < amount:
        await interaction.response.send_message(
            f"You do not have enough Beaned Bucks to invest {amount}.", ephemeral=True
        )
        return

    # Deduct the investment amount and update the portfolio.
    user_record["balance"] = current_balance - amount
    portfolio = user_record.get("portfolio", {})
    portfolio[stock] = portfolio.get(stock, 0) + shares
    user_record["portfolio"] = portfolio
    data[user_id] = user_record
    save_data(data)

    # Display the full float value without rounding.
    await interaction.response.send_message(
        f"Successfully invested {amount} Beaned Bucks in {stock} at {price} per share.\n"
        f"You now own {portfolio[stock]} shares of {stock}.\n"
        f"Your new balance is {user_record['balance']} Beaned Bucks."
    )
@bot.tree.command(
    name="portfolio",
    description="View your stock holdings and their current value.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(user="Optional: The user whose portfolio you want to see (defaults to yourself)")
async def portfolio(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    data = load_data()
    user_id = str(target.id)
    user_record = data.get(user_id, {"balance": 0, "portfolio": {}})
    portfolio_holdings = user_record.get("portfolio", {})

    # Load current stock prices (your stocks.json is a simple dict mapping stock symbols to prices).
    stock_prices = load_stocks()

    # Create the embed.
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
            name="Total Portfolio Value",
            value=f"{round(total_value, 2)} Beaned Bucks",
            inline=False
        )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="sellstock",
    description="Sell shares of a stock to receive Beaned Bucks.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    stock="The stock symbol you want to sell (e.g. ACME)",
    quantity="The number of shares you want to sell"
)
async def sell(interaction: discord.Interaction, stock: str, quantity: float):
    # Validate that the quantity is positive.
    if quantity <= 0:
        await interaction.response.send_message("Quantity must be greater than zero.", ephemeral=True)
        return

    # Load current stock data.
    stocks_data = load_stocks()
    stock = stock.upper()
    if stock not in stocks_data:
        await interaction.response.send_message("Invalid stock symbol.", ephemeral=True)
        return

    price = stocks_data[stock]
    sale_value = round(price * quantity, 2)

    # Load the user's data.
    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0, "portfolio": {}})
    portfolio = user_record.get("portfolio", {})

    # Check if the user owns enough shares (fractional).
    if stock not in portfolio or portfolio[stock] < quantity:
        await interaction.response.send_message("You do not own enough shares of that stock to sell.", ephemeral=True)
        return

    # Deduct the sold shares from the portfolio.
    portfolio[stock] -= quantity
    if portfolio[stock] <= 0:
        del portfolio[stock]
    user_record["portfolio"] = portfolio

    # Add the sale proceeds to the user's balance.
    user_record["balance"] += sale_value

    # Save updated data.
    data[user_id] = user_record
    save_data(data)

    await interaction.response.send_message(
        f"Successfully sold {quantity:.2f} shares of {stock} at {price} Beaned Bucks each for a total of {sale_value} Beaned Bucks.\n"
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
    # Count aces as 1, then add 10 if it won't bust
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
        # Hide the dealer's first card
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
    def __init__(self, player: discord.Member, bet: int):
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

        # Dealer's turn: hit until the dealer's hand value is at least 17.
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
        # Doubling is allowed only if the player has exactly two cards.
        if len(self.game.player_hand) != 2:
            await interaction.response.send_message("You can only double down on your first move (with exactly 2 cards).", ephemeral=True)
            return

        # Check if the player has enough funds to double down.
        # The additional cost is equal to the current bet.
        if not hasattr(self.game, 'remaining'):
            await interaction.response.send_message("Funds information missing.", ephemeral=True)
            return
        if self.game.remaining < self.game.bet:
            await interaction.response.send_message("You don't have enough funds to double down.", ephemeral=True)
            return

        # Deduct additional funds and double the bet.
        self.game.remaining -= self.game.bet
        self.game.bet *= 2
        print(f"[Blackjack] Doubling down. New bet: {self.game.bet}. Remaining funds: {self.game.remaining}")
        # Deal one card and automatically end the player's turn.
        self.game.player_hand.append(self.game.deck.pop())
        await self.end_game(interaction)
# Background task that updates the stock market periodically.

@tasks.loop(minutes=UPDATE_INTERVAL_MINUTES)
async def stock_market_loop():
    update_stock_prices()

@stock_market_loop.before_loop
async def before_stock_loop():
    await bot.wait_until_ready()

@tasks.loop(minutes=UPDATE_INTERVAL_MINUTES)
async def stock_market_loop():
    changes = update_stock_prices()
    
    # Create an embed for the stock update.
    embed = discord.Embed(
        title="Stock Market Update",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_footer(text="Prices update every 20 minute")
    
    # Add a field for each stock.
    for stock, change in changes.items():
        sign = "+" if change["abs"] >= 0 else ""
        field_value = (
            f"**Old:** {change['old']}\n"
            f"**New:** {change['new']}\n"
            f"**Change:** {sign}{change['abs']} ({sign}{change['perc']}%)"
        )
        embed.add_field(name=stock, value=field_value, inline=True)
    
    # Find the channel named "stocks" and send the embed.
    channel = discord.utils.get(bot.get_all_channels(), name="stocks")
    if channel is not None:
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to send embed: {e}")
    else:
        print("Channel '#stocks' not found.")



@bot.tree.command(
    name="stocks",
    description="View current stock prices, or view a specific stock's price history.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(stock="Optional: The stock symbol to view history for")
async def stocks(interaction: discord.Interaction, stock: Optional[str] = None):
    current_prices = load_stocks()
    
    # If no specific stock is provided, display current prices for all stocks.
    if stock is None:
        msg = "**Current Stock Prices:**\n"
        for sym, price in current_prices.items():
            msg += f"**{sym}**: {price} Beaned Bucks\n"
        await interaction.response.send_message(msg)
    else:
        stock = stock.upper()
        # Check if the stock exists in current data.
        if stock not in current_prices:
            await interaction.response.send_message(f"Stock symbol '{stock}' not found.", ephemeral=True)
            return

        # Retrieve current price.
        price = current_prices[stock]
        msg = f"**{stock}**\nCurrent Price: {price} Beaned Bucks\n\n"
        
        # Load the stock history.
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

@bot.tree.command(
    name="help",
    description="Displays a list of available commands and their descriptions.",
    guild=discord.Object(id=GUILD_ID)
)
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**Beaned Bot Help**\n\n"
        "**/blackjack [bet]** - Play a round of Blackjack using your Beaned Bucks. Place a bet and then choose to Hit, Stand, or Double Down.\n\n"
        "**/work** - Work to earn a random amount between 1 and 250 Beaned Bucks (usable every 10 minutes).\n\n"
        "**/daily** - Claim your daily reward of 500-5000 Beaned bucks every 24 hours.\n\n"
        "**/dailyboost** - Claim your daily reward of 5000-10000 Beaned bucks every 24 hours. (server boosters only).\n\n"
        "**/balance [user]** - Check your Beaned Bucks balance. If no user is provided, it defaults to your own balance.\n\n"
        "**/wheel [target]** - Timeout a user randomly for various durations if you have enough Beaned Bucks or an allowed role.\n\n"
        "**/joinnotification** - Join the notif notifications channel.\n\n"
        "**/leavenotification** - Leave the notif notifications channel\n\n"
        "**/portfolio** - Checks your stock portfolio\n\n"
        "**/stock [stock name]** - Checks the entire stock market, if stock name is included check that stocks history\n\n"
        "**/buystock [stock] [price]** - Buys an amount of stock equal to your price.\n\n"
        "**/sellstock [stock] [price]** - Sells an amount of stock equal to your price.\n\n"
        "**/roulette [amount] [bet]** - Plays a game of roulette with your amount and bet."
    )
    await interaction.response.send_message(help_text, ephemeral=True)

@bot.tree.command(
    name="work",
    description="Work and earn between 1 and 250 Beaned Bucks (once every 10 minutes).",
    guild=discord.Object(id=GUILD_ID)
)
async def work(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)
    now = datetime.datetime.now()
    
    # Retrieve or initialize user record, with "last_work" timestamp.
    user_record = data.get(user_id, {"balance": 0, "last_work": None})
    last_work_str = user_record.get("last_work")
    
    # Check if 10 minutes have passed since last work.
    if last_work_str:
        last_work = datetime.datetime.fromisoformat(last_work_str)
        if now - last_work < datetime.timedelta(minutes=10):
            remaining = datetime.timedelta(minutes=10) - (now - last_work)
            remaining_minutes = remaining.seconds // 60
            remaining_seconds = remaining.seconds % 60
            await interaction.response.send_message(
                f"You can work again in {remaining_minutes} minutes and {remaining_seconds} seconds.",
                ephemeral=True
            )
            return

    # Award a random amount between 1 and 250 Beaned Bucks.
    reward = random.randint(1, 250)
    user_record["balance"] += reward
    user_record["last_work"] = now.isoformat()
    data[user_id] = user_record
    save_data(data)
    
    await interaction.response.send_message(
        f"You worked and earned {reward} Beaned Bucks! Your new balance is {user_record['balance']} Beaned Bucks.",
        ephemeral=True
    )

# In your blackjack command, after validating the bet:
def is_blackjack(hand):
    """Return True if hand is a blackjack (exactly 2 cards with value 21)."""
    return len(hand) == 2 and get_hand_value(hand) == 21

@bot.tree.command(name="blackjack", description="Play a round of Blackjack using your Beaned Bucks.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(bet="The amount of Beaned Bucks you want to bet")
async def blackjack(interaction: discord.Interaction, bet: int):
    print(f"[Blackjack] Invoked by {interaction.user} with bet {bet}")
    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0})
    balance = user_record.get("balance", 0)
    print(f"[Blackjack] User record before game: {user_record}")
    
    if bet <= 0:
        await interaction.response.send_message("Bet must be greater than 0.", ephemeral=True)
        return
    if bet > balance:
        await interaction.response.send_message("You don't have enough Beaned Bucks to make that bet.", ephemeral=True)
        return

    # Create a new blackjack game.
    game = BlackjackGame(interaction.user, bet)
    # Store starting balance and remaining funds.
    game.start_balance = balance
    game.remaining = balance - bet

    # Check for blackjack immediately.
    if is_blackjack(game.player_hand):
        # Player has blackjack.
        if is_blackjack(game.dealer_hand):
            game.result = "tie"
        else:
            game.result = "win"
            # Apply 1.5x multiplier.
            game.bet = int(game.bet * 1.5)
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
    # Making the game public; remove ephemeral if you want visibility.
    await interaction.response.send_message(content=content, view=view, ephemeral=False)
    await view.wait()

    # Update the player's balance using the updated game.bet.
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


# --- Daily Slash Command ---
@bot.tree.command(name="daily", description="Claim your daily reward of 500-1000 Beaned Bucks (once every 24 hours).", guild=discord.Object(id=GUILD_ID))
async def daily(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)
    now = datetime.datetime.now()
    user_record = data.get(user_id, {"balance": 0, "last_daily": None})
    last_daily_str = user_record.get("last_daily")
    if last_daily_str:
        last_daily = datetime.datetime.fromisoformat(last_daily_str)
        if now - last_daily < datetime.timedelta(days=1):
            remaining = datetime.timedelta(days=1) - (now - last_daily)
            remaining_hours = remaining.seconds // 3600
            remaining_minutes = (remaining.seconds % 3600) // 60
            await interaction.response.send_message(
                f"You have already claimed your daily reward. Try again in {remaining_hours} hours and {remaining_minutes} minutes.",
                ephemeral=True
            )
            return
    reward = random.randint(500, 5000)
    user_record["balance"] += reward
    user_record["last_daily"] = now.isoformat()
    data[user_id] = user_record
    save_data(data)
    await interaction.response.send_message(f"You received {reward} Beaned Bucks! Your new balance is {user_record['balance']}.", ephemeral=True)

# --- Wheel Slash Command ---
@bot.tree.command(name="wheel", description="Timeout a user randomly with varying durations if you have at least 10,000 Beaned Bucks.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(target="The user to be timed out")
async def wheel(interaction: discord.Interaction, target: discord.Member):
    invoker = interaction.user
    has_allowed_role = any(role.name.lower() in [r.lower() for r in ALLOWED_ROLES] for role in invoker.roles)
    data = load_data()
    user_id = str(invoker.id)
    user_balance = data.get(user_id, {}).get("balance", 0)
    if not has_allowed_role:
        if user_balance < 10000:
            await interaction.response.send_message("You do not have permission to use this command. You must either have one of the allowed roles or at least 10,000 Beaned Bucks.", ephemeral=True)
            return
        else:
            data[user_id]["balance"] = user_balance - 10000
            save_data(data)
    options = [
        (60, "60 seconds"),
        (300, "5 minutes"),
        (600, "10 minutes"),
        (3600, "1 hour"),
        (86400, "1 day"),
        (604800, "1 week"),
    ]
    weights = [55, 20, 15, 5, 4, 1]
    duration_seconds, label = random.choices(options, weights=weights, k=1)[0]
    timeout_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=duration_seconds)
    try:
        await target.timeout(timeout_until)
        await interaction.response.send_message(f"{target.mention} has been timed out for {label}!")
    except Exception as e:
        print(f"Error during timeout: {e}")

        await interaction.response.send_message("Failed to timeout the user. Check my permissions.", ephemeral=True)

@bot.tree.command(
    name="dailyboost",
    description="Claim your daily booster reward (5,000-10,000 Beaned Bucks) every 24 hours)",
    guild=discord.Object(id=GUILD_ID)
)
async def dailyboost(interaction: discord.Interaction):
    # Check if the user is a server booster.
    if interaction.user.premium_since is None:
        await interaction.response.send_message("You must be a Server Booster to claim this reward.", ephemeral=True)
        return

    data = load_data()
    user_id = str(interaction.user.id)
    now = datetime.datetime.now()
    
    # Retrieve or initialize user record with a separate field for daily boost.
    user_record = data.get(user_id, {"balance": 0, "last_daily_boost": None})
    last_boost_str = user_record.get("last_daily_boost")
    
    # Check if the user has already claimed their boost reward within 24 hours.
    if last_boost_str:
        last_boost = datetime.datetime.fromisoformat(last_boost_str)
        if now - last_boost < datetime.timedelta(days=1):
            remaining = datetime.timedelta(days=1) - (now - last_boost)
            remaining_hours = remaining.seconds // 3600
            remaining_minutes = (remaining.seconds % 3600) // 60
            await interaction.response.send_message(
                f"You have already claimed your daily booster reward. Try again in {remaining_hours} hours and {remaining_minutes} minutes.",
                ephemeral=True
            )
            return

    # Award a random boost reward between 5,000 and 15,000 Beaned Bucks.
    reward = random.randint(5000, 15000)
    user_record["balance"] += reward
    user_record["last_daily_boost"] = now.isoformat()
    data[user_id] = user_record
    save_data(data)
    
    await interaction.response.send_message(
        f"You worked as a booster and earned {reward} Beaned Bucks! Your new balance is {user_record['balance']}.",
        ephemeral=True
    )

@bot.tree.command(
    name="pay",
    description="Transfer Beaned Bucks to another user.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(user="The user to transfer Beaned Bucks to", amount="The amount of Beaned Bucks to transfer")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int):
    payer_id = str(interaction.user.id)
    payee_id = str(user.id)
    data = load_data()

    # Ensure both payer and payee have an entry in the data.
    if payer_id not in data:
        data[payer_id] = {"balance": 0}
    if payee_id not in data:
        data[payee_id] = {"balance": 0}

    # Check that the transfer amount is positive.
    if amount <= 0:
        await interaction.response.send_message("Transfer amount must be greater than 0.", ephemeral=True)
        return

    payer_balance = data[payer_id].get("balance", 0)
    if payer_balance < amount:
        await interaction.response.send_message("You do not have enough Beaned Bucks to complete this transfer.", ephemeral=True)
        return

    # Subtract from payer and add to payee.
    data[payer_id]["balance"] = payer_balance - amount
    payee_balance = data[payee_id].get("balance", 0)
    data[payee_id]["balance"] = payee_balance + amount

    save_data(data)

    await interaction.response.send_message(
        f"You have transferred {amount} Beaned Bucks to {user.display_name}.",
        ephemeral=False
    )

# --- Voice State Update Event ---
@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != TARGET_USER_ID:
        return
    if before.channel is None and after.channel is not None:
        notif_channel = discord.utils.get(member.guild.text_channels, name="notif")
        if notif_channel is None:
            print("Channel #notif not found.")
            return
        role = discord.utils.get(member.guild.roles, name="notif")
        if role is None:
            print("Role 'notif' not found.")
            return
        await notif_channel.send(f"{role.mention} Alert: {member.mention} has joined a voice channel!")

@bot.tree.command(
    name="balance", 
    description="Show the Beaned Bucks balance of a user.",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(user="The user to check balance for (defaults to yourself if not provided).")
async def balance(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    # Default to the interaction user if no user is specified.
    target = user or interaction.user

    data = load_data()
    user_id = str(target.id)
    user_record = data.get(user_id, {"balance": 0})
    balance_value = user_record.get("balance", 0)
    
    await interaction.response.send_message(f"{target.display_name} has {balance_value} Beaned Bucks.")

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
async def roulette(interaction: discord.Interaction, bet: float, choice: str):
    # Validate bet amount.
    if bet <= 0:
        await interaction.response.send_message("Bet must be greater than 0.", ephemeral=True)
        return

    data = load_data()
    user_id = str(interaction.user.id)
    user_record = data.get(user_id, {"balance": 0})
    current_balance = user_record.get("balance", 0)
    if bet > current_balance:
        await interaction.response.send_message("You do not have enough Beaned Bucks for that bet.", ephemeral=True)
        return

    # Deduct the wager from the user's balance immediately.
    user_record["balance"] = current_balance - bet
    data[user_id] = user_record
    save_data(data)

    # Simulate the roulette spin (0-36)
    outcome = random.randint(0, 36)

    # Define red and black numbers (using typical European roulette colors)
    red_numbers = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    black_numbers = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

    # Determine the payout multiplier.
    multiplier = 0  # if remains 0, the bet loses
    win = False
    choice_lower = choice.lower()

    # If the choice is a digit (i.e. betting on a specific number):
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

    # Create an embed to display the result.
    embed = discord.Embed(
        title="Roulette Result",
        color=discord.Color.purple(),
        timestamp=datetime.datetime.utcnow()
    )
    embed.add_field(name="Outcome", value=str(outcome), inline=True)
    embed.add_field(name="Your Bet", value=choice, inline=True)
    embed.add_field(name="Wager", value=str(bet), inline=True)

    if win:
        # If winning, payout is wager returned plus winnings:
        winnings = bet * multiplier  # profit
        total_return = bet + winnings  # total returned
        embed.add_field(name="Result", value=f"WIN! Multiplier: {multiplier}x\nWinnings: {winnings} Beaned Bucks\nTotal Return: {total_return}", inline=False)
        # Add the winnings back to user's balance.
        user_record["balance"] += total_return
    else:
        embed.add_field(name="Result", value="LOSE!", inline=False)
    data[user_id] = user_record
    save_data(data)

    embed.set_footer(text=f"New Balance: {user_record['balance']} Beaned Bucks")
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    stock_market_loop.start()
bot.run(TOKEN)
