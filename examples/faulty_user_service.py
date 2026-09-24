"""Deliberately broken module for exercising the PR reviewer.

Mixes classic OWASP-style security flaws (for the Semgrep stage) with
plain logic/correctness bugs (for the LLM stage). Do not import this
into real application code.
"""

import hashlib
import os
import pickle
import random
import sqlite3
import subprocess

import requests
import yaml

API_KEY = "sk-live-51H8f9aQ0z0Y7f2xKp7vJd8n3mZq2vwT"  # hardcoded secret
DB_PATH = "users.db"


def get_user(username):
    # SQL injection: user input concatenated directly into the query
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE username = '" + username + "'"
    cursor.execute(query)
    return cursor.fetchone()


def run_backup(target_dir):
    # command injection via shell=True with unsanitized input
    subprocess.call("tar -czf backup.tar.gz " + target_dir, shell=True)


def load_config(path):
    with open(path) as f:
        # unsafe YAML load can execute arbitrary Python objects
        return yaml.load(f, Loader=yaml.Loader)


def deserialize_session(blob):
    # insecure deserialization of untrusted data
    return pickle.loads(blob)


def hash_password(password):
    # weak hash for password storage, no salt
    return hashlib.md5(password.encode()).hexdigest()


def generate_reset_token():
    # non-cryptographic RNG used for a security-sensitive token
    return str(random.randint(100000, 999999))


def fetch_avatar(url):
    # SSRF-prone request with TLS verification disabled
    return requests.get(url, verify=False, timeout=10)


def eval_discount_expression(expr, cart_total):
    # arbitrary code execution via eval on user-controlled input
    return eval(expr.replace("TOTAL", str(cart_total)))


def read_uploaded_file(filename):
    # path traversal: filename is not validated against a safe root
    with open("/var/uploads/" + filename) as f:
        return f.read()


# --- logic / correctness bugs below, no security ruleset needed ---

def add_item(item, basket=[]):
    # mutable default argument: `basket` is shared across every call
    basket.append(item)
    return basket


def average(values):
    total = 0
    for i in range(len(values)):
        total += values[i]
    # off-by-one: dividing by len(values) + 1 undercounts, and this
    # also throws ZeroDivisionError for an empty list
    return total / (len(values) + 1)


def get_discount_tier(points):
    # `is` used for integer value comparison instead of `==`
    if points is 1000:
        return "gold"
    return "standard"


def close_stale_sessions(sessions):
    for i in range(len(sessions)):
        if sessions[i].expired:
            # mutating a list while iterating over its indices skips
            # the element right after every removed one
            del sessions[i]


def load_users_safely():
    try:
        with open("users.json") as f:
            return f.read()
    except:
        # bare except swallows everything, including KeyboardInterrupt,
        # and hides the real error
        pass


def write_log(message):
    f = open("app.log", "a")
    f.write(message + "\n")
    # file handle is never closed: resource leak


def is_admin(user):
    # inverted boolean logic: this returns True for everyone EXCEPT admins
    if user.role != "admin":
        return True
    return False
