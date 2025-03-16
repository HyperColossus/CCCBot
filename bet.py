import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import random
import datetime
from globals import RIOT_IDS, UPDATE_INTERVAL_MINUTES, GUILD_ID
from utils import load_data, save_data
from typing import Optional
import pytz
import cassiopeia as cass
from cassiopeia import Summoner
import asyncio

cass.set_riot_api_key("RGAPI-25a25f68-abf6-46ee-a7b8-6648d818b620")

def load_data():
    try:
        with open(RIOT_IDS, "r") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Riot Ids data is not a dictionary.")
            return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        default_data = {}  
        save_data(default_data)
        return default_data
    
def save_data(data):
    with open(RIOT_IDS, "w") as f:
        json.dump(data, f, indent=4)

class betCog(commands.Cog):
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="setid", description="Set your Riot ID and Region, Your Name and Tagline are CASE SENSETIVE")
    @app_commands.describe(name = "Riot name", tagline = "Riot tagline", region = "Riot region")
    async def riotID(self, interaction: discord.Interaction, name: str, tagline: str, region: str):
        try:
            # Load existing data
            data = load_data()
            user_id = str(interaction.user.id)
            
            # Get account and summoner info
            account = cass.get_account(name= name, tagline= tagline , region = region.capitalize)
            summoner = account.summoner
            
            # Save data
            data[user_id] = {
                "name": name,
                "tagline": tagline,
                "region": region,
                "puuid": account.puuid
            }
            
            save_data(data)
            
            await interaction.response.send_message(f"Successfully set your Riot ID to {name}#{tagline} in {region}!")
        
        except Exception as e:
            await interaction.response.send_message(f"Error setting Riot ID: {str(e)}", ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name = "queue", description= "Use this when you start q so the bot can find your game")
    async def startQ(self, interaction: discord.Interaction):
        data = load_data()
        user_id = str(interaction.user.id)
        user_data = data.get(user_id, {"puuid": "blank", "region": "blank", "name": "blank", "tagline": "blank"})

        if not user_data:
            await interaction.response.send_message("⚠️ No Riot ID found! Use `/setid` first.", ephemeral=True)
            return

        try:
            name = user_data["name"]
            puuid = user_data["puuid"]  
            region = user_data["region"]
            tagline = user_data["tagline"]

            await interaction.response.send_message("🔍 Searching for an active match... Please wait.", ephemeral=True)
            tries = 0
            max_tries = 30

            while tries < max_tries:  
                try:
                    summoner = cass.get_summoner(puuid=puuid, region=region)

                    current_match = summoner.current_match

                    if current_match is not None:
                        await interaction.followup.send(f"🎉 You are now in a match! Match ID: {current_match.id}")

                except Exception as e:
                    await interaction.response.send_message(f"⚠️ Error fetching match: {str(e)}", ephemeral=True)
                    return
                
                tries += 1
                await asyncio.sleep(10)
            await interaction.followup.send("⏱️ Timed out waiting for a match. Please try again when you're in a game.", ephemeral=True)

        except Exception as e:
            # This will only execute if there's an error before the first response is sent
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ Error fetching match: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ Error fetching match: {str(e)}", ephemeral=True)    


async def setup(bot: commands.Bot):
    print("Loading BetCog...")
    await bot.add_cog(betCog(bot))