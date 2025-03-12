#includes /help so i can better keep track of it

import discord
from discord import app_commands
from discord.ext import commands, tasks
from globals import TOKEN, GUILD_ID, TARGET_MEMBER_ID, TARGET_USER_ID, DATA_FILE, ALLOWED_ROLES, STOCK_FILE, STOCK_HISTORY_FILE, UPDATE_INTERVAL_MINUTES, LOTTERY_FILE, AFK_CHANNEL_ID

class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="help", description="Displays a list of available commands and their descriptions.")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Beaned Bot Help",
            color=discord.Color.blue(),
            description="Below are the commands available, grouped by category."
        )
        
        general = (
            "**/balance [user]** - Check your Beaned Bucks balance (defaults to your own).\n"
            "**/leaderboard** - Check the networth, time, timealone, timeafk leaderboards.\n" 
            "**/daily** - Get your daily beaned bucks.\n"
            "**/dailyboost** - Get your daily beaned bucks. (boosters only)\n"
            "**/joinnotification** - Join the notif notifications channel.\n"
            "**/leavenotification** - Leave the notif notifications channel."
        )
        
        gambling = (
            "**/blackjack [bet]** - Play a round of Blackjack using your Beaned Bucks.\n"
            "**/roulette [amount] [bet]** - Play a game of roulette with your bet.\n"
            "**/wheel [target]** - Timeout a user randomly if you have enough Beaned Bucks or the allowed role."
        )
        
        stocks = (
            "**/portfolio** - Check your stock portfolio and profit (invested vs. earned).\n"
            "**/stock [stock name]** - View current stock prices or a specific stock's history.\n"
            "**/buystock [stock] [price]** - Buy stock at your specified price.\n"
            "**/sellstock [stock] [price]** - Sell stock at your specified price."
        )
        
        lottery = (
            "**/lotteryticket [numbers]** - Buy a lottery ticket for 5,000 Beaned Bucks; choose 5 unique numbers (1-60).\n"
            "**/lotterydraw** - Force a lottery draw (restricted to lottery admins).\n"
            "**/lotterytotal** - View the current lottery jackpot."
        )
        
        embed.add_field(name="General", value=general, inline=False)
        embed.add_field(name="Gambling", value=gambling, inline=False)
        embed.add_field(name="Stocks", value=stocks, inline=False)
        embed.add_field(name="Lottery", value=lottery, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    print("Loading HelpCog...")
    await bot.add_cog(HelpCog(bot))