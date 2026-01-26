#!/usr/bin/env python3
"""
Create Admin User for A.R.C.H.I.E.
"""
import psycopg2
from werkzeug.security import generate_password_hash
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'archie')
DB_USER = os.getenv('DB_USER', 'archie')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')

# Admin configuration
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@kytranempowerment.com')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'changeme')

def create_admin_user():
    """Create admin user"""
    try:
        # Connect to database
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cur = conn.cursor()
        
        # Check if admin exists
        cur.execute("SELECT id FROM users WHERE username = %s", (ADMIN_USERNAME,))
        if cur.fetchone():
            print(f"❌ Admin user '{ADMIN_USERNAME}' already exists!")
            cur.close()
            conn.close()
            return False
        
        # Hash password
        password_hash = generate_password_hash(ADMIN_PASSWORD)
        
        # Create admin user
        cur.execute("""
            INSERT INTO users (username, email, password_hash, role, is_active, is_admin)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (ADMIN_USERNAME, ADMIN_EMAIL, password_hash, 'admin', True, True))
        
        user_id = cur.fetchone()[0]
        conn.commit()
        
        # Initialize emotional state
        cur.execute("""
            INSERT INTO archie_emotional_state (user_id, current_mood, mood_intensity, relationship_strength)
            VALUES (%s, %s, %s, %s)
        """, (user_id, 'excited', 0.85, 0.5))
        
        # Add first milestone
        cur.execute("""
            INSERT INTO relationship_milestones (user_id, milestone_type, description, emotional_significance)
            VALUES (%s, %s, %s, %s)
        """, (user_id, 'first_conversation', 'Admin user created - A.R.C.H.I.E. ready!', 1.0))
        
        conn.commit()
        
        print("✅ Admin user created successfully!")
        print(f"   Username: {ADMIN_USERNAME}")
        print(f"   Email: {ADMIN_EMAIL}")
        print(f"   Password: {ADMIN_PASSWORD}")
        print("")
        print("⚠️  IMPORTANT: Change the password after first login!")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        return False

if __name__ == '__main__':
    create_admin_user()
