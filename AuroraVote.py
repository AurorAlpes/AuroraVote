import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import string
import re
import os
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

# Intents pour récupérer les membres et les rôles
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

# Stockage des votes et des configurations de vote
votes = {}
vote_config = {}
vote_open = {}
vote_keys = {}  # Stocker les clés pour chaque vote
vote_participants = {}  # Stocker les participants de chaque vote

class VoteButton(discord.ui.Button):
    def __init__(self, label, reponse, question, status_message):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.reponse = reponse
        self.question = question
        self.status_message = status_message  # Message d'état

    async def callback(self, interaction: discord.Interaction):
        user_roles = [role.name for role in interaction.user.roles]
        config = vote_config[self.question]

        # Vérifier si l'utilisateur a déjà voté
        if interaction.user.id in config["votes"]:
            await interaction.response.send_message("Vous avez déjà voté.", ephemeral=True)
            return

        # Vérifier les rôles de l'utilisateur
        valid_role = False
        for role in config["poids"]:
            if role in user_roles:
                valid_role = True
                break

        if not valid_role:
            await interaction.response.send_message("Vous n'avez pas le rôle nécessaire pour voter.", ephemeral=True)
            return

        # Générer une clé unique pour l'utilisateur
        key = ''.join(random.choices(string.ascii_letters + string.digits + string.punctuation, k=16))

        # Enregistrer le vote avec la clé
        config["votes"][interaction.user.id] = self.reponse
        config["vote_counts"][self.reponse] += 1  # Compter le vote
        config["voters"][interaction.user.id] = next(role for role in user_roles if role in config["poids"])  # Enregistrer le rôle
        vote_keys[self.question][key] = self.reponse  # Associer la clé au vote

        # Ajouter l'utilisateur à la liste des participants
        if self.question not in vote_participants:
            vote_participants[self.question] = []
        vote_participants[self.question].append(interaction.user.name)

        # Mettre à jour le message d'état
        total_voters = len(config["votes"])
        time_remaining = self.status_message.content.split('|')[1].strip()  # Récupérer le temps restant
        self.status_message.content = f"Votants : {total_voters} | {time_remaining}"
        await self.status_message.edit(content=self.status_message.content)

        # Envoyer la clé en privé au votant
        try:
            await interaction.user.send(f"A voté ! Votre clé unique et confidentielle pour le vote **{self.question}** est : {key}")
        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas pu vous envoyer un message privé, veuillez vérifier vos paramètres de confidentialité.", ephemeral=True)
            return

        await interaction.response.send_message(f"Votre vote pour '{self.reponse}' a été pris en compte.", ephemeral=True)

@bot.tree.command(name="createauroravote", description="Créer un vote Aurora avec des boutons pour voter.")
@app_commands.describe(question="La question du vote", reponses="Les réponses possibles, séparées par des virgules", roles="Les rôles autorisés à voter, séparées par des virgules", poids="Les poids des rôles autorisés, séparées par des virgules", temps="Temps du vote en secondes")
async def create_vote(interaction: discord.Interaction, question: str, reponses: str, roles: str, poids: str, temps: int):
    if interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Création du vote en cours...", ephemeral=True)  # Réponse initiale

        reponses_list = reponses.split(",")
        roles_list = [role.strip() for role in roles.split(",")]
        poids_list = [int(p.strip()) for p in poids.split(",")]

        if len(roles_list) != len(poids_list):
            await interaction.followup.send("Le nombre de rôles et de poids doit correspondre.", ephemeral=True)
            return

        vote_config[question] = {
            "reponses": reponses_list,
            "poids": {},
            "votes": {},
            "vote_counts": {reponse: 0 for reponse in reponses_list},
            "voters": {}  # Enregistrement des votants et de leurs rôles
        }

        votes[question] = {}
        vote_open[question] = True
        vote_keys[question] = {}  # Initialiser le stockage des clés pour ce vote
        vote_participants[question] = []  # Initialiser la liste des participants

        # Configurer les poids des rôles
        for role_name, poids_value in zip(roles_list, poids_list):
            if role_name.startswith("<@&") and role_name.endswith(">"):  # Vérifier le format de la mention
                role_id = int(role_name[3:-1])  # Extraire l'ID du rôle
                role_obj = interaction.guild.get_role(role_id)
                if role_obj:
                    vote_config[question]["poids"][role_obj.name] = poids_value
                else:
                    await interaction.followup.send(f"Le rôle mentionné n'existe pas : {role_name}", ephemeral=True)
                    return
            else:
                await interaction.followup.send(f"Format de mention invalide pour le rôle : {role_name}", ephemeral=True)
                return

        view = discord.ui.View()

        # Message d'état initial
        status_message = await interaction.channel.send("Votants : 0 | Temps restant : N/A")

        for reponse in reponses_list:
            button = VoteButton(label=reponse.strip(), reponse=reponse.strip(), question=question, status_message=status_message)
            view.add_item(button)

        await interaction.followup.send(f"Vote créé : **{question}**. Cliquez sur un bouton pour voter.", view=view)

        # Si le temps est supérieur à 0, commencez le compte à rebours
        if temps > 0:
            for remaining in range(temps, 0, -1):
                await asyncio.sleep(1)
                total_voters = len(vote_config[question]["votes"])
                time_left_message = f"Votants : {total_voters} | Temps restant : {remaining} secondes"
                await status_message.edit(content=time_left_message)

            vote_open[question] = False
            await afficher_resultats(interaction.channel, question)
        else:
            await status_message.edit(content="Votants : 0 | Temps restant : Indéfini")

    else:
        await interaction.response.send_message("Vous n'avez pas les permissions nécessaires pour créer un vote.", ephemeral=True)


async def afficher_resultats(channel, question):
    if question not in votes or question not in vote_open:
        return

    # Nettoyer le nom de la question pour enlever les caractères spéciaux
    cleaned_question = re.sub(r'[\\/*?:"<>|]', "", question)

    # Initialisation des résultats
    results = {reponse: 0 for reponse in vote_config[question]["reponses"]}
    total_votes_per_role = {role: 0 for role in vote_config[question]["poids"]}

    # Calculer le nombre de votants par rôle
    for user_id, reponse in vote_config[question]["votes"].items():
        user_role = vote_config[question]["voters"][user_id]
        total_votes_per_role[user_role] += 1

    # Calculer le score final
    for user_id, reponse in vote_config[question]["votes"].items():
        user_role = vote_config[question]["voters"][user_id]
        poids = vote_config[question]["poids"][user_role]
        votes_count = total_votes_per_role[user_role]

        # Ajouter le poids proportionnel pour chaque réponse
        if votes_count > 0:
            results[reponse] += poids / votes_count

    # **Normalisation des résultats** pour atteindre 100% si certains groupes n'ont pas voté
    total_score = sum(results.values())
    
    if total_score < 100 and total_score > 0:  # Eviter une division par zéro
        scaling_factor = 100 / total_score
        results = {reponse: score * scaling_factor for reponse, score in results.items()}

    # Afficher les résultats
    result_message = "\n".join(f"{reponse}: {score:.2f}%" for reponse, score in results.items())
    await channel.send(f"Résultats du vote pour **'{question}'** :\n{result_message}")

    # Générer le fichier texte des participants
    participants_file_path = f"{cleaned_question}_participants.txt"
    with open(participants_file_path, "w") as f:
        f.write("Liste des participants ayant voté :\n")
        for participant in vote_participants[question]:
            f.write(f"{participant}\n")

    # Générer le fichier texte des clés et des votes
    keys_file_path = f"{cleaned_question}_keys_votes.txt"
    with open(keys_file_path, "w") as f:
        f.write("Liste des clés et des votes anonymes :\n")
        
        # Créer une liste de tuples (clé, vote) et les mélanger
        keys_votes = list(vote_keys[question].items())
        random.shuffle(keys_votes)  # Mélanger la liste des clés et des votes

        for key, vote in keys_votes:
            f.write(f"Clé: {key} - Vote: {vote}\n")

    # Envoyer les fichiers dans le salon du vote
    if os.path.exists(participants_file_path):
        await channel.send(file=discord.File(participants_file_path))
    else:
        await channel.send("Erreur : le fichier des participants n'a pas été généré.")

    if os.path.exists(keys_file_path):
        await channel.send(file=discord.File(keys_file_path))
    else:
        await channel.send("Erreur : le fichier des clés et des votes n'a pas été généré.")


@bot.tree.command(name="closeauroravote", description="Fermer un vote Aurora et afficher les résultats.")
async def close_vote(interaction: discord.Interaction, question: str):
    if interaction.user.guild_permissions.administrator:
        if question in vote_open and vote_open[question]:
            vote_open[question] = False
            await afficher_resultats(interaction.channel, question)
        else:
            await interaction.response.send_message("Le vote n'est pas ouvert ou n'existe pas.", ephemeral=True)
    else:
        await interaction.response.send_message("Vous n'avez pas les permissions nécessaires pour fermer un vote.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Bot {bot.user} est connecté.")
    await bot.tree.sync()  # Synchroniser les commandes avec Discord
    print("Commandes synchronisées.")

# Démarrer le bot avec le token
keep_alive()
bot.run(token)
