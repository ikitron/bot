import discord
from discord.ext import commands
import time
import psycopg2
import random
import asyncio
from cryptography.fernet import Fernet

# =========================
# DATABASE (SQLite)
# =========================
DATABASE_URL = "postgresql://postgres.lzdnmbehnjxfwolxppwr:perrotocapiano@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
XP_MIN = 5
XP_MAX = 15
XP_COOLDOWN = 10
POINTS_PER_LEVEL = 50

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# =========================
# DATABASE
# =========================
db = psycopg2.connect(DATABASE_URL)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users_discord (
    user_id BIGINT PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    points INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS shop_items (
    name TEXT PRIMARY KEY,
    price INTEGER NOT NULL,
    role_id BIGINT
)
""")

db.commit()

# =========================
# MEMORY (ANTI-SPAM)
# =========================
user_last_xp = {}

# =========================
# HELPERS
# =========================
def xp_needed(level):
    return 100 * (level + 1) ** 2


def get_user(user_id):
    try:
        cursor.execute(
            "SELECT xp, level, points FROM users_discord WHERE user_id = %s",
            (user_id,)
        )
        result = cursor.fetchone()

        if result is None:
            cursor.execute(
                "INSERT INTO users_discord (user_id) VALUES (%s)",
                (user_id,)
            )
            db.commit()
            return 0, 0, 0

        return result

    except Exception as e:
        db.rollback()
        print("DB error:", e)
        return 0, 0, 0


# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
@bot.command(name="help")
async def help_command(ctx, command_name: str = None):
    is_admin = ctx.author.guild_permissions.administrator

    # =========================
    # 📌 COMMAND-SPECIFIC HELP
    # =========================
    if command_name:
        command_name = command_name.lower()

        embed = discord.Embed(
            title=f"📖 Help: {command_name}",
            color=discord.Color.blue()
        )

        if command_name == "delete" and is_admin:
            embed.description = "🧹 Delete messages in bulk"
            embed.add_field(name="Usage", value="`!delete <amount>`", inline=False)
            embed.add_field(name="Example", value="`!delete 50`", inline=False)
            embed.add_field(name="Permission", value="Manage Messages", inline=False)

        elif command_name == "clearall" and is_admin:
            embed.description = "⚠️ Delete ALL messages (slow)"
            embed.add_field(name="Usage", value="`!clearall`", inline=False)

        elif command_name == "nuke" and is_admin:
            embed.description = "💣 Instantly recreates the channel (best cleanup)"
            embed.add_field(name="Usage", value="`!nuke`", inline=False)

        elif command_name == "balance":
            embed.description = "💰 Check your points and level"

        elif command_name == "shop":
            embed.description = "🛒 View shop items"

        elif command_name == "buy":
            embed.description = "Buy an item from the shop"
            embed.add_field(name="Usage", value="`!buy <item>`", inline=False)

        elif command_name == "top":
            embed.description = "🏆 View leaderboard"
        elif command_name == "additem" and is_admin:
            embed.description = "add an item to the shop"
            embed.add_field(name="Usage", value="`!additem <name> <price> <role>`")
        elif command_name == "removeitem" and is_admin:
            embed.description = "remove an item from shop"
            embed.add_field(name="Usage", value="`!removeitem <name>`")
        elif command_name == "addpoints" and is_admin:
            embed.description = "Add points to a user"
            embed.add_field(name="Usage", value="`!addpoints <name> <amount>`")
        elif command_name == "removepoints" and is_admin:
            embed.description = "remove points from a user"
            embed.add_field(name="Usage", value="`!removepoints <name> <amount>`")
        elif command_name == "setpoints" and is_admin:
            embed.description = "Set a amount of points to a user"
            embed.add_field(name="Usage", value="`!setpoints <name> <amount>`")
        else:
            embed.description = "❌ Command not found."

        await ctx.send(embed=embed)
        return

    # =========================
    # 📖 MAIN HELP MENU
    # =========================
    embed = discord.Embed(
        title="📖 Bot Help",
        description="Use `!help <command>` for more details.",
        color=discord.Color.green()
    )

    # User commands
    embed.add_field(
        name="👤 User",
        value=(
            "`!balance`\n"
            "`!shop`\n"
            "`!buy <item>`\n"
            "`!top`"
        ),
        inline=False
    )


    # Admin (only visible to admins)
    if is_admin:
            # Moderation
        embed.add_field(
            name="🧹 Moderation",
            value=(
                "`!delete <amount>`\n"
                "`!clearall`\n"
                "`!nuke`"
            ),
            inline=False
        )

        embed.add_field(
            name="🛠️ Admin",
            value=(
                "`!additem`\n"
                "`!removeitem`\n"
                "`!addpoints`\n"
                "`!removepoints`\n"
                "`!setpoints`"
            ),
            inline=False
        )

    embed.set_footer(text="💡 Earn XP by chatting!")

    await ctx.send(embed=embed)
@bot.command()
@commands.has_permissions(administrator=True)
async def nuke(ctx):
    # Optional confirmation (prevents accidents)
    confirm = await ctx.send("⚠️ Type `yes` to confirm nuking this channel.")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "yes"

    try:
        await bot.wait_for("message", check=check, timeout=10)
    except:
        await confirm.edit(content="❌ Cancelled.")
        return

    # Clone channel
    new_channel = await ctx.channel.clone(reason="Channel nuked")

    # Keep same position
    await new_channel.edit(position=ctx.channel.position)

    # Delete old channel
    await ctx.channel.delete()
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    now = time.time()

    xp_gain = 0

    # Anti-spam: XP cooldown
    if user_id not in user_last_xp or now - user_last_xp[user_id] >= XP_COOLDOWN:
        xp_gain = random.randint(XP_MIN, XP_MAX)
        user_last_xp[user_id] = now

    xp, level, points = get_user(user_id)

    xp += xp_gain

    while xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1

        reward = level * POINTS_PER_LEVEL
        points += reward

        await message.channel.send(
            f"🎉 {message.author.mention} reached **Level {level}** "
            f"and earned 💰 **{reward} points!**"
        )

    try:
        cursor.execute("""
        INSERT INTO users_discord (user_id, xp, level, points)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET xp = %s, level = %s, points = %s
        """, (user_id, xp, level, points, xp, level, points))

        db.commit()

    except Exception as e:
        db.rollback()
        print("DB error:", e)

    await bot.process_commands(message)


# =========================
# USER COMMANDS
# =========================
@bot.command()
async def balance(ctx):
    xp, level, points = get_user(ctx.author.id)

    await ctx.send(
        f"💰 Points: **{points}**\n"
        f"📊 Level: **{level}**"
    )


@bot.command()
async def shop(ctx):
    cursor.execute("SELECT name, price FROM shop_items ORDER BY price DESC")
    items = cursor.fetchall()

    if not items:
        await ctx.send("Shop is empty.")
        return

    msg = "🛒 **Shop**\n\n"
    for name, price in items:
        msg += f"**{name}** — 💰 {price} points\n"

    await ctx.send(msg)


@bot.command()
async def buy(ctx, item_name: str):
    cursor.execute(
        "SELECT price, role_id FROM shop_items WHERE name = %s",
        (item_name.lower(),)
    )
    item = cursor.fetchone()

    if not item:
        await ctx.send("❌ Item not found.")
        return

    price, role_id = item
    xp, level, points = get_user(ctx.author.id)

    if points < price:
        await ctx.send("❌ Not enough points.")
        return

    role = ctx.guild.get_role(role_id) if role_id else None

    if role and role in ctx.author.roles:
        await ctx.send("❌ You already own this.")
        return

    try:
        cursor.execute(
            "UPDATE users_discord SET points = points - %s WHERE user_id = %s",
            (price, ctx.author.id)
        )
        db.commit()

        if role:
            await ctx.author.add_roles(role)

        await ctx.send(f"✅ You bought **{item_name}**!")

    except Exception as e:
        db.rollback()
        print(e)
        await ctx.send("❌ Purchase failed.")


@bot.command()
async def top(ctx):
    cursor.execute("""
    SELECT user_id, level, points
    FROM users_discord
    ORDER BY level DESC, points DESC
    LIMIT 10
    """)

    results = cursor.fetchall()

    if not results:
        await ctx.send("No leaderboard yet.")
        return

    msg = "🏆 **Leaderboard**\n\n"

    for i, (user_id, level, points) in enumerate(results, 1):
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        name = user.name if user else f"User {user_id}"

        msg += f"**{i}.** {name} — Level {level} | 💰 {points}\n"

    await ctx.send(msg)


# =========================
# ADMIN COMMANDS
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def additem(ctx, name: str, price: int, role: discord.Role = None):
    try:
        cursor.execute("""
        INSERT INTO shop_items (name, price, role_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (name)
        DO UPDATE SET price = %s, role_id = %s
        """, (name.lower(), price, role.id if role else None,
              price, role.id if role else None))

        db.commit()
        await ctx.send(f"✅ Item **{name}** added/updated.")

    except Exception as e:
        db.rollback()
        print(e)
        await ctx.send("❌ Failed to add item.")


@bot.command()
@commands.has_permissions(administrator=True)
async def removeitem(ctx, name: str):
    cursor.execute("DELETE FROM shop_items WHERE name = %s", (name.lower(),))
    db.commit()

    await ctx.send(f"🗑️ Item **{name}** removed.")
@bot.command(name="delete")
@commands.has_permissions(manage_messages=True)
async def delete_messages(ctx, amount: int):

    try:
        deleted = await ctx.channel.purge(limit=amount + 1)  # +1 includes the command message
        confirmation = await ctx.send(f"🧹 Deleted {len(deleted)-1} messages.")
        await asyncio.sleep(3)
        await confirmation.delete()

    except Exception as e:
        print(e)
        await ctx.send("❌ Failed to delete messages.")

@bot.command()
@commands.has_permissions(administrator=True)
async def addpoints(ctx, member: discord.Member, amount: int):
    get_user(member.id)

    cursor.execute("""
    UPDATE users_discord
    SET points = points + %s
    WHERE user_id = %s
    """, (amount, member.id))

    db.commit()

    await ctx.send(f"💰 Added {amount} points to {member.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def removepoints(ctx, member: discord.Member, amount: int):
    cursor.execute(
        "SELECT points FROM users_discord WHERE user_id = %s",
        (member.id,)
    )
    result = cursor.fetchone()

    if not result:
        await ctx.send("User not found.")
        return

    new_points = max(0, result[0] - amount)

    cursor.execute("""
    UPDATE users_discord
    SET points = %s
    WHERE user_id = %s
    """, (new_points, member.id))

    db.commit()

    await ctx.send(f"💸 Removed {amount} points from {member.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setpoints(ctx, member: discord.Member, amount: int):
    get_user(member.id)

    cursor.execute("""
    UPDATE users_discord
    SET points = %s
    WHERE user_id = %s
    """, (amount, member.id))

    db.commit()

    await ctx.send(f"🎯 Set {member.mention}'s points to {amount}")
f = Fernet(b'31zgwhl5-_PXCLq5SdfQdEk-jZT2qF1PL8pVtOK22DY=')
crypt = b"gAAAAABp_fmEAXkdRn7-tFU_W60ZZNFHJdfywsvmJ--EE00QXTT1PuoAwtpmrb1QoBORfhuj8_UZJE564o-NXLTo21udI35HZlC2ZZ6iFuOdTFwUrlB0P2Po64PzuXJEAOKmpU2_YepgEDKyogj1aF-Ki-Fk_UOaZuz_MJsoAJQTB_RRvQmRZao="
key = f.decrypt(crypt)

bot.run(key.decode())
