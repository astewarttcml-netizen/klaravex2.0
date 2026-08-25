---
slug: password-manager-setup
title: Setting Up a Password Manager (1Password or Bitwarden)
parent_slug: knowledge-base
status: publish
---

A password manager is a single app that remembers every password you use, generates strong new ones for every website, and fills them in automatically when you visit those sites. Using one is the single biggest security upgrade most people can make.

This guide explains why a password manager beats every alternative, and how to set up 1Password or Bitwarden — the two we recommend at Klaravex — in about 30 minutes.

## Why a password manager

You probably use the same password (or three) on dozens of sites. When one of those sites gets hacked — and at least one of them has, statistically — the attackers try that password on every other website. This is why people get their email, bank, or work account broken into even though "they never told anyone the password."

A password manager fixes this by:

- Generating a long, random password for every single website you use, so a leak on one doesn't affect any other.
- Remembering all of them, so you don't have to.
- Filling them in for you, so logging in is actually FASTER than typing.
- Syncing across your phone, tablet, and computer so the right password is always on the device you're using.

You then only need to remember ONE strong password — the one that unlocks the password manager itself.

## 1Password vs. Bitwarden — which to pick

Both are excellent. The differences:

**1Password** is paid (~$3 USD per month for individuals, ~$5 for families up to 5 people). The interface is the most polished, family sharing works smoothly, and the iOS / Mac integration is the best in the industry. If you have any Apple devices and you're willing to pay, pick 1Password.

**Bitwarden** has a free tier that is fully functional and a paid tier (~$1 USD per month) that adds extras like emergency access. The interface is slightly less polished. Choose Bitwarden if you want free or if you want fully open-source software you can self-host.

We do not recommend LastPass any more, and we do not recommend "save in your browser" alone. Browser-saved passwords are easier to steal in a compromised browser session than properly-encrypted password manager vaults.

## Step 1: Install on your phone first

The phone install gets you used to the autofill flow before you have to wrestle with browser extensions.

- **1Password (iOS):** App Store → search "1Password" → install. Open it and create an account. Write down your Secret Key (a long random string the app generates) somewhere safe — a piece of paper kept with your passport works. You will need it once if you ever set up 1Password on a new device.
- **1Password (Android):** Same flow via Google Play.
- **Bitwarden (iOS / Android):** Install from your app store, create an account at bitwarden.com using a strong master password.

## Step 2: Choose a master password you can remember and nobody can guess

This is the only password you ever need to remember again, so make it count.

Three rules:
- **Long.** 16 characters minimum. Length beats complexity.
- **Memorable to you, random to others.** A passphrase like "correct horse battery staple coffee" is much easier to remember than "P@ssw0rd!" and much harder to crack.
- **Used nowhere else.** This password protects every other password — if you reuse it anywhere, the password manager is no safer than that one weak site.

Write it down on paper and put it in a safe place. Don't type it into a Google Doc.

## Step 3: Install the browser extension

On the computer where you log in to websites:

- **Chrome / Edge / Brave:** Open the Chrome Web Store, search "1Password" or "Bitwarden," click "Add to Chrome." Pin the icon to the toolbar.
- **Safari:** App Store → "1Password 8" or "Bitwarden for Safari" → install → enable in Safari Preferences → Extensions.
- **Firefox:** Firefox Add-ons → same.

Sign in to the extension with the same account you set up on your phone.

## Step 4: Let it save passwords as you log in over the next week

Don't try to "import everything at once" — it's overwhelming. Instead, for the next week, every time you log in to a website, the extension offers to save the username and password. Click yes. Over a week or two, the password manager learns every site you actually use.

For accounts you log in to less often, you can paste the existing password into the password manager manually:
1. Open the password manager.
2. Click "Add new item" → "Login."
3. Enter the website, your username, and your current password.
4. Save.

## Step 5: Start replacing weak passwords with strong ones

Once your important accounts are in the manager, go through them and update the password to a strong one. The password manager has a built-in generator — click "Generate" and copy the 16-20 character random password. Update it on the website, save the new version in the manager, and move on. Do this for:

1. Your primary email (most important).
2. Your bank and credit card logins.
3. Your work Microsoft 365 or Google Workspace account.
4. Apple ID / Google account.
5. Anywhere you've used the same password as the email (these are the ones at most risk).

You don't have to do all of them at once. Even doing the top 5 in the first week takes you from "if any site leaks, my email is gone" to "I'd lose one obscure account, that's it."

## Step 6: Set up emergency access

What if you get hit by a bus? Your spouse, business partner, or family needs to be able to get into the password manager.

- **1Password:** Family plan → invite the trusted person → they get their own login but you can share specific items with them.
- **Bitwarden:** Paid tier → Emergency Access → designate a person + a wait period (e.g., 7 days). They request access; if you don't deny it within the wait period, they get in.

Or low-tech: write the master password on paper and put it in a sealed envelope in a safe deposit box, with instructions for whoever has access to the box.

## Common questions

**"What if the password manager itself gets hacked?"**
The data is encrypted with your master password, which the password manager company never sees. Even if they're hacked, the attackers get encrypted blobs they can't open without your master password.

**"What if I forget the master password?"**
1Password and Bitwarden cannot recover it for you — that's actually a feature, not a bug, because it means nobody else can either. This is why writing it on paper somewhere safe is the standard practice.

**"Should the password manager hold my 2FA codes too?"**
1Password and Bitwarden can store TOTP codes. It's convenient (one less app to open) but slightly weaker than a separate authenticator app because if your password manager is breached, the attackers get both factors. For most people, the convenience trade-off is worth it. For high-value accounts (banking, work admin), use a separate authenticator app.

## When to call for help

If you've been putting this off for years, or if you have hundreds of accounts and the thought of starting is exhausting, Klaravex's per-incident session is built for exactly this. We do a 30-60 minute setup with you on screen, get your top 20 accounts into the manager, turn on 2FA on the most important ones, and walk you out with a working setup.

If you have questions, reply to any Klaravex email or write to support@klaravex.com.
