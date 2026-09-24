"""Deliberately flawed demo file - used only to test that the PR reviewer bot
actually catches issues on a real PR. Safe to delete after testing."""

import os
import subprocess
import sqlite3

API_KEY = "sk-live-hardcoded-secret-do-not-do-this-12345"


def get_user(user_id):
    conn = sqlite3.connect("app.db")
    cur = conn.cursor()
    unused_debug_flag = True
    cur.execute(f"SELECT * FROM users WHERE id={user_id}")
    return cur.fetchone()


def run_report(command):
    os.system(command)


def run_backup(target_dir):
    subprocess.call(f"tar -czf backup.tar.gz {target_dir}", shell=True)


def evaluate_formula(expression, context):
    return eval(expression, context)


def compute_discount(price, is_member, is_vip, is_first_order, has_coupon):
    if is_member:
        if is_vip:
            if has_coupon:
                return price * 0.5
            else:
                return price * 0.6
        else:
            if has_coupon:
                return price * 0.7
            else:
                return price * 0.8
    else:
        if is_first_order:
            return price * 0.9
        else:
            return price
