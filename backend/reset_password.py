#!/usr/bin/env python3
"""
DockMon Password Reset Tool
Command-line utility to reset user passwords
"""

import sys
import argparse
import getpass
from config.paths import DATABASE_PATH
from database import DatabaseManager


def main():
    parser = argparse.ArgumentParser(description="DockMon Password Reset Tool")
    parser.add_argument("username", nargs="?", help="Username to reset password for")
    parser.add_argument("--password", "-p", help="New password (if not provided, will be generated)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode - prompts for password")
    parser.add_argument("--list", "-l", action="store_true", help="List all usernames")

    args = parser.parse_args()

    # Initialize database with centralized path
    db = DatabaseManager(DATABASE_PATH)

    # List users if requested
    if args.list:
        users = db.list_users()
        if users:
            print("Available users:")
            for user in users:
                print(f"  - {user}")
        else:
            print("No users found in database.")
        sys.exit(0)

    # Get username - if not provided, check if there's only one user or default to 'admin'
    username = args.username
    if not username:
        users = db.list_users()
        if not users:
            print("Error: No users found in database.")
            sys.exit(1)
        elif len(users) == 1:
            username = users[0]
            print(f"Using username: {username}")
        elif 'admin' in users:
            username = 'admin'
            print(f"Using default username: admin")
        else:
            print("Error: Multiple users exist. Please specify a username.")
            print("Available users:")
            for user in users:
                print(f"  - {user}")
            print("\nUsage: python reset_password.py <username>")
            sys.exit(1)

    new_password = args.password

    # Interactive mode - prompt for password
    if args.interactive:
        while True:
            password1 = getpass.getpass("Enter new password (min 8 characters): ")
            if len(password1) < 8:
                print("Password must be at least 8 characters long.")
                continue

            password2 = getpass.getpass("Confirm new password: ")
            if password1 != password2:
                print("Passwords do not match. Please try again.")
                continue

            new_password = password1
            break

    # Reset the password
    result = db.reset_user_password(username, new_password)

    if result is None:
        print(f"Error: User '{username}' not found.")
        sys.exit(1)

    print(f"✓ Password reset successfully for user: {username}")

    if not args.password and not args.interactive:
        # Password was auto-generated
        print(f"New password: {result}")
        print("\n⚠️  Please save this password securely. You will be prompted to change it on next login.")
    else:
        print("\n✓ You can now login with your new password.")
        print("   The user will be prompted to change the password on next login.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)