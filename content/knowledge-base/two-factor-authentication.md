---
slug: two-factor-authentication
title: Two-Factor Authentication (2FA) — Why You Need It and How to Set It Up
parent_slug: knowledge-base
status: publish
---

Two-factor authentication — sometimes called 2FA, MFA, or "multi-factor authentication" — is the single most effective protection against having one of your accounts stolen. It is short for "you need two things to log in: something you know (your password) and something you have (your phone or a hardware key)." Even if someone steals your password, they cannot log in without that second thing.

This guide walks through what 2FA is, the three common kinds, and how to turn it on for the accounts that matter most.

## Why 2FA matters more than a strong password

A strong password helps, but every year billions of passwords leak from one website or another. Once a leaked password is in an attacker's hands, they try it on every other site you might have an account at — your email, your bank, your work Microsoft 365 account. This is called "credential stuffing" and it is the most common way regular people get hacked today.

2FA breaks that attack. The attacker has your password, but they don't have your phone, so they cannot log in.

## The three kinds of 2FA, ranked

Not all 2FA is equally good. From strongest to weakest:

1. **Hardware security key** (YubiKey, Google Titan, Apple Passkey on iPhone). The strongest option. A small USB or NFC device that physically proves you are you. Resistant to phishing.
2. **Authenticator app** (Google Authenticator, Microsoft Authenticator, Authy, 1Password). A free app on your phone that generates a 6-digit code that changes every 30 seconds. Strong and easy.
3. **Text message (SMS) code**. The website sends a code to your phone number when you try to log in. Better than nothing, but the weakest option — attackers can sometimes hijack your phone number ("SIM swapping") to receive the codes themselves.

If a site offers an authenticator app or hardware key, use that. Use SMS only if it is the only option.

## Step 1: Pick an authenticator app

For most people, an authenticator app is the right balance of strong and easy. Install one on your phone before you start turning on 2FA.

- **iPhone:** Microsoft Authenticator (free, from the App Store) or 1Password (if you already use a password manager).
- **Android:** Microsoft Authenticator or Google Authenticator (free, from the Play Store).
- **All platforms:** Authy is also good and has backups if you change phones.

Pick one and stick with it. Switching authenticator apps later is annoying because each 2FA setup has to be redone.

## Step 2: Turn on 2FA for the accounts that matter most

In order of importance:

1. **Your primary email** (Gmail, Outlook, Yahoo, iCloud). This is the most important account in your life because anyone who controls your email can reset every other password you have. Turn 2FA on here first.
2. **Your banking and credit card accounts.** Mercury, Chase, your credit union, your credit card login.
3. **Microsoft 365 / Google Workspace work account.** If you use one of these for work, your IT team can also require this; turn it on yourself before they make you.
4. **Apple ID or Google account.** These control your phone, your apps, and often your other devices.
5. **Anywhere you store money or files** — Amazon, PayPal, Venmo, Dropbox, iCloud, Google Drive.
6. **Social media.** Facebook, Instagram, LinkedIn, X (Twitter).

For each one:

1. Log in with your username and password as usual.
2. Open the account's "Security" settings (sometimes called "Sign-in & security" or "Login").
3. Find "Two-factor authentication" or "2-Step Verification" and click "Turn on" or "Get started."
4. Choose "Authenticator app" if offered.
5. The website shows a QR code on screen.
6. Open the authenticator app on your phone, tap the "+" button, and scan the QR code with your phone's camera.
7. The app starts generating a 6-digit code. Enter that code on the website to confirm it worked.
8. **Important:** the website also shows you backup codes (usually 8-10 codes printed once). Save these somewhere safe — they let you log in if your phone is lost or broken. A piece of paper in a drawer is fine. Saving them in your password manager (1Password, Bitwarden) is even better.

## Step 3: What if you lose your phone?

This is the question that scares people away from 2FA. Three layers of safety:

- **Backup codes** (Step 2 above) let you log in once even with no phone.
- **A second device** — if you set up Authy or 1Password, you can install it on a tablet too, and both devices generate the same codes.
- **Account recovery flows** — most sites have a "I lost my 2FA" form. This usually takes a few days and requires proof of identity, but it works.

Practical tip: print your backup codes when you set up 2FA and put the printout in the same place as your passport or social security card.

## Step 4: Be careful with prompts you didn't ask for

If your phone suddenly buzzes asking "Do you want to log in?" and you weren't trying to log in — say NO. Someone has your password and is trying to trick you into approving their login. Change the password for that account immediately.

This is called "MFA fatigue" or "push bombing" and it is one of the few ways attackers have figured out around 2FA. Don't approve anything you didn't initiate.

## When you're ready for the next step

A hardware security key (like a YubiKey, around $50) is the strongest protection available today. If you handle a lot of money, run a business, or have been compromised in the past, it is worth the investment. You plug it into your USB port or tap it to your phone, and the website is convinced you're you.

If you're not sure where to start with hardware keys, or if you'd like help getting 2FA turned on for all of your important accounts at once, this is exactly the kind of thing a Klaravex per-incident session is built for. We can walk you through it on screen in about 30 minutes.

If you have questions, reply to any Klaravex email or write to support@klaravex.com.
