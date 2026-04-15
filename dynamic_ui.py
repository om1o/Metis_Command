import streamlit as st
import json
from streamlit_lottie import st_lottie

# 1. PAGE CONFIGURATION
st.set_page_config(page_title="Project Metis", layout="centered", initial_sidebar_state="collapsed")

# 2. THE CYBER-LUXURY CSS INJECTION
# This block executes Steps 1 through 4 of the Brand Identity Playbook.
def inject_custom_css():
    st.markdown("""
        <style>
        /* Step 1: Import Luxury Typography */
        @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&family=Inter:wght@300;400;600&display=swap');

        /* Step 2 & 3: Deep Obsidian Background & Global Font */
        .stApp {
            background-color: #0B0C10;
            font-family: 'Inter', sans-serif;
            color: #FFFFFF;
        }

        /* Step 3: Glassmorphism Chat Containers & 16px Geometry */
        .stChatMessage {
            background: rgba(255, 255, 255, 0.03) !important;
            backdrop-filter: blur(10px) !important;
            -webkit-backdrop-filter: blur(10px) !important;
            border-radius: 16px !important;
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 20px;
            margin-bottom: 15px;
        }

        /* Step 4: The Electric Cyan Glow for User Inputs & Buttons */
        .stTextInput>div>div>input {
            background-color: rgba(0, 0, 0, 0.5) !important;
            color: #FFFFFF !important;
            border-radius: 16px !important;
            border: 1px solid rgba(102, 252, 241, 0.3) !important;
            transition: all 0.3s ease;
        }
        
        /* The Neon Hover Effect */
        .stTextInput>div>div>input:focus {
            border: 1px solid #66FCF1 !important;
            box-shadow: 0 0 15px rgba(102, 252, 241, 0.4) !important;
        }

        /* Fira Code for Code Blocks */
        code {
            font-family: 'Fira Code', monospace !important;
            background-color: rgba(0, 0, 0, 0.8) !important;
            color: #66FCF1 !important;
            border-radius: 8px !important;
        }
        </style>
    """, unsafe_allow_html=True)

# 3. THE LOTTIE ANIMATION LOADER (Step 5)
def load_lottiefile(filepath: str):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

# --- APP EXECUTION ---
inject_custom_css()

# The UI Layout
st.markdown("<h1 style='text-align: center; color: #FFFFFF; font-weight: 300;'>METIS <span style='color: #66FCF1;'>//</span> CORE</h1>", unsafe_allow_html=True)

# Fake chat history for visual testing
with st.chat_message("assistant"):
    st.write("System initialized. I am online, Director. How shall we proceed?")
    st.code("System.Status = 'Awaiting Command';", language="python")

with st.chat_message("user"):
    st.write("Run the startup sequence and load the custom animations.")

# Check for Lottie File
lottie_anim = load_lottiefile("metis_custom_loader.json")
if lottie_anim:
    st.write("Loading Animation Preview:")
    st_lottie(lottie_anim, height=150, key="loader")
else:
    st.markdown("<p style='color: gray; text-align: center;'>[metis_custom_loader.json not found in directory. Add it to see the animation.]</p>", unsafe_allow_html=True)

# The User Input Box
prompt = st.chat_input("Enter command sequence...")
if prompt:
    st.write(f"Command received: {prompt}")