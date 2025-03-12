import discord
from discord import app_commands
from discord.ext import commands
import random
import datetime
from utils import load_data, save_data 
from globals import GUILD_ID

class RouletteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="roulette", description="Play roulette. Bet on a number or category (odd, even, red, black, 1st12, 2nd12, 3rd12).")
    @app_commands.describe(bet="Amount you'd like to bet", choice="0-36, odd, even, red, black, 1st12, 2nd12, 3rd12")
    async def roulette(self, interaction: discord.Interaction, bet: str, choice: str):
        data = load_data()
        user_id = str(interaction.user.id)
        user_record = data.get(user_id, {"balance": 0})
        current_balance = float(user_record.get("balance", 0))
        
        if bet.lower() == "all":
            bet_value = current_balance
        else:
            try:
                bet_value = float(bet)
            except ValueError:
                await interaction.response.send_message("Invalid bet amount.", ephemeral=True)
                return

        if bet_value <= 0:
            await interaction.response.send_message("Bet must be greater than 0.", ephemeral=True)
            return
        if bet_value > current_balance:
            await interaction.response.send_message("You do not have enough Beaned Bucks for that bet.", ephemeral=True)
            return

        #deduct the wager
        user_record["balance"] = current_balance - bet_value
        data[user_id] = user_record
        save_data(data)

        outcome = random.randint(0, 36)
        red_numbers = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        black_numbers = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}
        multiplier = 0
        win = False
        choice_lower = choice.lower()

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
            await interaction.response.send_message(
                "Invalid bet choice. Please choose a number (0-36) or one of: odd, even, red, black, 1st12, 2nd12, 3rd12.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Roulette Result",
            color=discord.Color.purple(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Outcome", value=str(outcome), inline=True)
        embed.add_field(name="Your Bet", value=choice, inline=True)
        embed.add_field(name="Wager", value=str(bet_value), inline=True)

        if win:
            winnings = bet_value * multiplier
            total_return = bet_value + winnings
            embed.add_field(
                name="Result",
                value=f"WIN! Multiplier: {multiplier}x\nWinnings: {winnings} Beaned Bucks\nTotal Return: {total_return}",
                inline=False
            )
            user_record["balance"] += total_return
        else:
            embed.add_field(name="Result", value="LOSE!", inline=False)

        data[user_id] = user_record
        save_data(data)
        embed.set_footer(text=f"New Balance: {user_record['balance']} Beaned Bucks")
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(RouletteCog(bot))
