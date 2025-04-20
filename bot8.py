import os
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from tinydb import TinyDB, Query
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fuzzywuzzy import process  # For fuzzy matching

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot Token
TOKEN = "7605644480:AAFL5GnPPS5ruAGorhPw-6XpvAQyWjw_Iu8"

# Spotify API Credentials
SPOTIFY_CLIENT_ID = "22dd1971754b46c78c6286f937fadb58"
SPOTIFY_CLIENT_SECRET = "3e632f22f9e5475bb73c5988f2d1a9f5"

# Initialize Spotify API
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))

# Database for caching & tracking searches
db = TinyDB("music_db.json")
search_history = Query()

# Menu Keyboard
menu_button = [
    [KeyboardButton("📀 Download full albums"), KeyboardButton("🎤 Browse artist")],
    [KeyboardButton("🔍 Search Songs"), KeyboardButton("🔎 Advanced Search")]
]
reply_markup = ReplyKeyboardMarkup(menu_button, resize_keyboard=True)

# Command handler for '/start'
async def start(update: Update, context: CallbackContext):
    try:
        await update.message.reply_text(
            "🎵 Welcome to Tune Wizard! Choose an option from the menu below:", reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in start handler: {e}")

# Function to handle menu options
async def menu_handler(update: Update, context: CallbackContext):
    text = update.message.text

    if text == "📀 Download full albums":
        await update.message.reply_text("💿 Enter the album name:")
        context.user_data["action"] = "download_album"  # Set action to download album
    elif text == "🎤 Browse artist":
        await update.message.reply_text("🎵 Enter the artist's name to browse their songs and albums.")
        context.user_data["action"] = "browse_artist"  # Set action to browse artist
    elif text == "🔍 Search Songs":
        await update.message.reply_text("🔍 Enter the name of the song you want to search for.")
        context.user_data["action"] = "search_song"  # Set action to search song
    elif text == "🔎 Advanced Search":
        await update.message.reply_text("🔎 Enter the song name and artist in the format: 'Song Name - Artist Name'.")
        context.user_data["action"] = "advanced_search"  # Set action for advanced search
    else:
        await update.message.reply_text("❓ Invalid option. Please select from the menu.")

# Function to search for an artist
async def search_artist(artist_name):
    try:
        query = f"artist:{artist_name}"
        logger.info(f"Searching Spotify for: {query}")
        results = sp.search(q=query, type='artist', limit=1)
        
        if results['artists']['items']:
            artist = results['artists']['items'][0]
            artist_id = artist['id']
            top_tracks = sp.artist_top_tracks(artist_id)['tracks']  # Get all top tracks
            return artist, top_tracks
        else:
            logger.warning(f"No artist found for: {query}")
            return None, None
    except Exception as e:
        logger.error(f"Error searching artist: {e}")
        return None, None

# Function to search for an album
async def search_album(album_name):
    try:
        query = f"album:{album_name}"
        logger.info(f"Searching Spotify for: {query}")
        results = sp.search(q=query, type='album', limit=5)  # Search for up to 5 albums
        
        if results['albums']['items']:
            # Return the first album and its tracks
            album = results['albums']['items'][0]
            album_id = album['id']
            tracks = sp.album_tracks(album_id)['items']
            return album, tracks
        else:
            logger.warning(f"No album found for: {query}")
            return None, None
    except Exception as e:
        logger.error(f"Error searching album: {e}")
        return None, None

# Function to search for a song
async def search_song(song_name):
    try:
        query = f"track:{song_name}"
        logger.info(f"Searching Spotify for: {query}")
        results = sp.search(q=query, type='track', limit=1)
        
        if results['tracks']['items']:
            track = results['tracks']['items'][0]
            return track
        else:
            logger.warning(f"No song found for: {query}")
            return None
    except Exception as e:
        logger.error(f"Error searching song: {e}")
        return None

# Function to perform advanced search (song + artist)
async def advanced_search(song_name, artist_name=None):
    try:
        if artist_name:
            query = f"track:{song_name} artist:{artist_name}"
        else:
            query = f"track:{song_name}"
        
        logger.info(f"Searching Spotify for: {query}")
        results = sp.search(q=query, type='track', limit=5)  # Search for up to 5 tracks
        
        if results['tracks']['items']:
            # Return the first track
            track = results['tracks']['items'][0]
            return track
        else:
            logger.warning(f"No song found for: {query}")
            return None
    except Exception as e:
        logger.error(f"Error in advanced search: {e}")
        return None

# Function to perform fuzzy matching for incorrect lyrics
async def fuzzy_search_song(user_input):
    try:
        # Fetch a list of popular songs (you can cache this for better performance)
        results = sp.search(q="year:2020-2023", type='track', limit=50)
        tracks = results['tracks']['items']
        
        # Extract song names for fuzzy matching
        song_names = [track['name'] for track in tracks]
        
        # Perform fuzzy matching
        best_match, score = process.extractOne(user_input, song_names)
        
        if score > 70:  # Only consider matches with a score above 70
            for track in tracks:
                if track['name'] == best_match:
                    return track
        return None
    except Exception as e:
        logger.error(f"Error in fuzzy search: {e}")
        return None

# Optimized asynchronous song downloading
executor = ThreadPoolExecutor()

async def download_song_to_memory_async(query, output_dir="/tmp"):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, download_song_to_memory, query, output_dir)

# Optimized function to download a song from YouTube
def download_song_to_memory(query, output_dir="/tmp"):
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 10,
        "extract_flat": True,
        "outtmpl": f"{output_dir}/{query}.%(ext)s"
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logger.info(f"Searching YouTube for: {query}")
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            if info and 'entries' in info:
                url = info['entries'][0]['url']
                logger.info(f"Downloading from URL: {url}")
                ydl.download([url])
                file_path = f"{output_dir}/{query}.mp3"
                if os.path.exists(file_path):
                    return file_path
            else:
                logger.warning("No YouTube results found.")
    except Exception as e:
        logger.error(f"Error downloading song: {e}")
    return None

# Message handler for browsing artist
async def handle_browse_artist(update: Update, context: CallbackContext):
    try:
        artist_name = update.message.text
        await update.message.reply_text(f"🔎 Searching for artist: {artist_name}...")

        # Search for the artist
        artist, top_tracks = await search_artist(artist_name)
        if artist and top_tracks:
            # Store tracks in user_data for pagination
            context.user_data["tracks"] = top_tracks

            # Send artist info and picture
            artist_info = f"🎤 *{artist['name']}*\n\n"
            artist_info += f"🌍 *Genres:* {', '.join(artist['genres'])}\n"
            artist_info += f"👥 *Followers:* {artist['followers']['total']}\n"
            artist_info += f"🎶 *Popularity:* {artist['popularity']}/100\n"

            if artist['images']:
                await update.message.reply_photo(photo=artist['images'][0]['url'], caption=artist_info, parse_mode='Markdown')
            else:
                await update.message.reply_text(artist_info, parse_mode='Markdown')

            # Send list of top tracks with pagination
            keyboard = create_track_keyboard(top_tracks)
            await update.message.reply_text("🎵 *Top Tracks:*\n⬇️ Select a track to download:", reply_markup=keyboard)
        else:
            await update.message.reply_text("⚠️ Artist not found. Please check the name.")
    except Exception as e:
        await update.message.reply_text("❗ Something went wrong while processing your request. Please try again later.")
        logger.error(f"Error in browsing artist: {e}")

# Function to create an inline keyboard for track selection with pagination
def create_track_keyboard(tracks, page=0, tracks_per_page=5):
    start = page * tracks_per_page
    end = start + tracks_per_page
    tracks_slice = tracks[start:end]

    keyboard = []
    for i, track in enumerate(tracks_slice, start=start + 1):
        keyboard.append([InlineKeyboardButton(f"{i}. {track['name']}", callback_data=f"track_{track['id']}")])

    # Add pagination buttons
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"page_{page - 1}"))
    if end < len(tracks):
        pagination_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"page_{page + 1}"))

    if pagination_buttons:
        keyboard.append(pagination_buttons)

    return InlineKeyboardMarkup(keyboard)

# Callback handler for track selection and pagination
async def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("track_"):
        # Handle track selection
        track_id = data.split("_")[1]
        await download_and_send_track(query, track_id, context)
    elif data.startswith("page_"):
        # Handle pagination
        page = int(data.split("_")[1])
        await update_song_list(query, page, context)

# Function to download and send a track
async def download_and_send_track(query, track_id, context: CallbackContext):
    try:
        track = sp.track(track_id)
        track_name = track['name']
        await query.edit_message_text(f"🔎 Downloading: {track_name}...")

        # Download the song
        song_path = await download_song_to_memory_async(track_name)
        if song_path:
            # Send the downloaded song as a new message
            await query.message.reply_audio(audio=open(song_path, 'rb'))
            os.remove(song_path)  # Clean up the file

            # Update the original message to indicate the song has been downloaded
            original_text = query.message.text
            updated_text = f"{original_text}\n\n✅ Downloaded: {track_name}"
            await query.edit_message_text(updated_text, reply_markup=query.message.reply_markup)
        else:
            await query.message.reply_text("⚠️ Error downloading the song. Please try again.")
    except Exception as e:
        await query.message.reply_text("❗ Something went wrong while processing your request. Please try again later.")
        logger.error(f"Error in track selection: {e}")

# Function to update the song list for pagination
async def update_song_list(query, page, context: CallbackContext):
    try:
        tracks = context.user_data.get("tracks")
        if not tracks:
            await query.message.reply_text("⚠️ No tracks found. Please try again.")
            return

        keyboard = create_track_keyboard(tracks, page)
        await query.edit_message_text(query.message.text, reply_markup=keyboard)
    except Exception as e:
        await query.message.reply_text("❗ Something went wrong while processing your request. Please try again later.")
        logger.error(f"Error in pagination: {e}")

# Message handler for downloading full albums
async def handle_album_download(update: Update, context: CallbackContext):
    try:
        album_name = update.message.text
        await update.message.reply_text(f"🔎 Searching for album: {album_name}...")

        # Search for the album
        album, tracks = await search_album(album_name)
        if album and tracks:
            await update.message.reply_text(f"🎵 Found album: {album['name']}. Starting download...")

            # Start the download process in the background
            asyncio.create_task(download_and_send_album(update, album['name'], tracks))
        else:
            await update.message.reply_text("⚠️ Album not found. Please check the name.")
    except Exception as e:
        await update.message.reply_text("❗ Something went wrong while processing your request. Please try again later.")
        logger.error(f"Error in album download: {e}")

# Function to download and send all tracks of an album
async def download_and_send_album(update: Update, album_name, tracks):
    try:
        for track in tracks:
            track_name = track['name']
            await update.message.reply_text(f"⬇️ Downloading: {track_name}...")
            song_path = await download_song_to_memory_async(track_name)
            if song_path:
                await update.message.reply_audio(audio=open(song_path, 'rb'))
                os.remove(song_path)  # Clean up the file
            else:
                await update.message.reply_text(f"⚠️ Error downloading: {track_name}")
    except Exception as e:
        await update.message.reply_text("❗ Something went wrong while processing your request. Please try again later.")
        logger.error(f"Error in album download: {e}")

# Message handler for searching songs
async def handle_song_search(update: Update, context: CallbackContext):
    try:
        song_name = update.message.text
        await update.message.reply_text(f"🔎 Searching for song: {song_name}...")

        # Search for the song
        track = await search_song(song_name)
        if track:
            track_name = track['name']
            artist_name = track['artists'][0]['name']
            await update.message.reply_text(f"🎵 Found: {track_name} by {artist_name}. Downloading...")

            # Download the song
            song_path = await download_song_to_memory_async(track_name)
            if song_path:
                await update.message.reply_audio(audio=open(song_path, 'rb'))
                os.remove(song_path)  # Clean up the file
            else:
                await update.message.reply_text("⚠️ Error downloading the song. Please try again.")
        else:
            # If no exact match, try fuzzy search
            await update.message.reply_text("🔍 No exact match found. Trying fuzzy search...")
            track = await fuzzy_search_song(song_name)
            if track:
                track_name = track['name']
                artist_name = track['artists'][0]['name']
                await update.message.reply_text(f"🎵 Found: {track_name} by {artist_name}. Downloading...")

                # Download the song
                song_path = await download_song_to_memory_async(track_name)
                if song_path:
                    await update.message.reply_audio(audio=open(song_path, 'rb'))
                    os.remove(song_path)  # Clean up the file
                else:
                    await update.message.reply_text("⚠️ Error downloading the song. Please try again.")
            else:
                await update.message.reply_text("⚠️ Song not found. Please check the name.")
    except Exception as e:
        await update.message.reply_text("❗ Something went wrong while processing your request. Please try again later.")
        logger.error(f"Error in song search: {e}")

# Message handler for advanced search
async def handle_advanced_search(update: Update, context: CallbackContext):
    try:
        # Expecting input in the format "Song Name - Artist Name" or just "Song Name"
        input_text = update.message.text
        if " - " in input_text:
            song_name, artist_name = input_text.split(" - ", 1)
        else:
            song_name = input_text
            artist_name = None

        await update.message.reply_text(f"🔎 Searching for song: {song_name} by {artist_name or 'any artist'}...")

        # Perform advanced search
        track = await advanced_search(song_name, artist_name)
        if track:
            track_name = track['name']
            artist_name = track['artists'][0]['name']
            await update.message.reply_text(f"🎵 Found: {track_name} by {artist_name}. Downloading...")

            # Download the song
            song_path = await download_song_to_memory_async(track_name)
            if song_path:
                await update.message.reply_audio(audio=open(song_path, 'rb'))
                os.remove(song_path)  # Clean up the file
            else:
                await update.message.reply_text("⚠️ Error downloading the song. Please try again.")
        else:
            await update.message.reply_text("⚠️ Song not found. Please check the name and try again.")
    except Exception as e:
        await update.message.reply_text("❗ Something went wrong while processing your request. Please try again later.")
        logger.error(f"Error in advanced search: {e}")

# Main function to run the bot
def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot is running...")
    application.run_polling()

# Function to handle text messages
async def handle_text(update: Update, context: CallbackContext):
    text = update.message.text

    # Check if the user is performing a specific action
    if "action" in context.user_data:
        if context.user_data["action"] == "download_album":
            await handle_album_download(update, context)
            context.user_data["action"] = None  # Reset action
        elif context.user_data["action"] == "browse_artist":
            await handle_browse_artist(update, context)
            context.user_data["action"] = None  # Reset action
        elif context.user_data["action"] == "search_song":
            await handle_song_search(update, context)
            context.user_data["action"] = None  # Reset action
        elif context.user_data["action"] == "advanced_search":
            await handle_advanced_search(update, context)
            context.user_data["action"] = None  # Reset action
    else:
        # If no action is set, assume the user is selecting a menu option
        await menu_handler(update, context)

if __name__ == "__main__":
    main()