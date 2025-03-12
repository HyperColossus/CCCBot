#lottery.py
import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import datetime
import asyncio
from zoneinfo import ZoneInfo
from globals import LOTTERY_FILE, GUILD_ID, ALLOWED_ROLES
from utils import load_data, save_data

def load_lottery():
    try:
        with open(LOTTERY_FILE, "r") as f:
            data = json.load(f)
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
    drawn_numbers = random.sample(range(1, 61), 5)
    drawn_set = set(drawn_numbers)
    print(f"[Lottery] Drawn Numbers: {drawn_numbers}")

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

    winning_tickets = [t for t in tickets if t["raw_multiplier"] > 0]
    total_raw = sum(t["raw_multiplier"] for t in winning_tickets)

    payouts = {}
    if total_raw > 0:
        for ticket in winning_tickets:
            payout_fraction = ticket["raw_multiplier"] / total_raw
            payout = jackpot * payout_fraction
            uid = ticket["user_id"]
            payouts[uid] = payouts.get(uid, 0) + payout

    new_jackpot = jackpot - sum(payouts.values()) + 25000
    lottery_data["Jackpot"] = new_jackpot
    lottery_data["Tickets"] = []
    save_lottery(lottery_data)
    return drawn_numbers, payouts

class LotteryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        #start the daily lottery draw task.
        self.daily_task = tasks.loop(hours=24)(self.daily_lottery_draw)
        self.daily_task.before_loop(self.before_daily_lottery_draw)
        self.daily_task.start()

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="lotteryticket", description="Buy a lottery ticket for 5,000 Beaned Bucks. Choose 5 unique numbers from 1 to 60.")
    async def lotteryticket(self, interaction: discord.Interaction, numbers: str):
        try:
            chosen_numbers = [int(n) for n in numbers.split()]
        except ValueError:
            await interaction.response.send_message("Invalid numbers. Please enter 5 numbers separated by spaces.", ephemeral=True)
            return

        if len(chosen_numbers) != 5 or len(set(chosen_numbers)) != 5 or any(n < 1 or n > 60 for n in chosen_numbers):
            await interaction.response.send_message("You must provide 5 unique numbers between 1 and 60.", ephemeral=True)
            return

        user_data = load_data()
        user_id = str(interaction.user.id)
        user_record = user_data.get(user_id, {"balance": 0})
        if user_record.get("balance", 0) < 5000:
            await interaction.response.send_message("You do not have enough Beaned Bucks to buy a lottery ticket.", ephemeral=True)
            return

        user_record["balance"] -= 5000
        user_data[user_id] = user_record
        save_data(user_data)

        lottery_data = load_lottery()
        lottery_data["Jackpot"] = lottery_data.get("Jackpot", 100000) + 5000
        ticket = {"user_id": user_id, "numbers": sorted(chosen_numbers)}
        lottery_data["Tickets"].append(ticket)
        save_lottery(lottery_data)

        await interaction.response.send_message(f"Ticket purchased with numbers: {sorted(chosen_numbers)}. 5000 Beaned Bucks deducted.", ephemeral=False)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="lotterytotal", description="View the current lottery jackpot.")
    async def lotterytotal(self, interaction: discord.Interaction):
        lottery_data = load_lottery()
        jackpot = lottery_data.get("Jackpot", 100000)
        await interaction.response.send_message(f"The current lottery jackpot is {jackpot} Beaned Bucks.", ephemeral=False)
        
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="lotterydraw", description="Perform the lottery draw. (Restricted to lottery admins.)")
    async def lotterydraw(self, interaction: discord.Interaction):
        if not any(role.name.lower() == ALLOWED_ROLES for role in interaction.user.roles):
            await interaction.response.send_message("You do not have permission to run the lottery draw.", ephemeral=True)
            return
        drawn_numbers, payouts = lottery_draw()
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

    async def daily_lottery_draw(self):
        now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        target_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        if now_et >= target_et:
            target_et += datetime.timedelta(days=1)
        delay = (target_et - now_et).total_seconds()
        print(f"[Lottery] Waiting {delay} seconds until daily lottery draw.")
        await asyncio.sleep(delay)
        drawn_numbers, payouts = lottery_draw()
        user_data = load_data()
        winners_msg = ""
        if payouts:
            for uid, amount in payouts.items():
                record = user_data.get(uid, {"balance": 0})
                record["balance"] = record.get("balance", 0) + amount
                user_data[uid] = record
                member = self.bot.get_guild(GUILD_ID).get_member(int(uid))
                name = member.display_name if member else f"User {uid}"
                winners_msg += f"{name} wins {amount:.2f} Beaned Bucks.\n"
            save_data(user_data)
        else:
            winners_msg = "No winning tickets this draw."
        channel = discord.utils.get(self.bot.get_all_channels(), name="bot-output")
        if channel:
            await channel.send(f"Daily Lottery Draw at 4pm ET:\nDrawn Numbers: {drawn_numbers}\n{winners_msg}")
        else:
            print("Channel not found for lottery.")

    async def before_daily_lottery_draw(self):
        now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        target_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        if now_et >= target_et:
            target_et += datetime.timedelta(days=1)
        delay = (target_et - now_et).total_seconds()
        print(f"Waiting {delay} seconds until next 4pm ET.")
        await asyncio.sleep(delay)

async def setup(bot: commands.Bot):
    print("Loading LotteryCog...")
    await bot.add_cog(LotteryCog(bot))
