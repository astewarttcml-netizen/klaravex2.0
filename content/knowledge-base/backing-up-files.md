---
slug: backing-up-files
title: Backing Up Your Files — The Simple Setup that Saves You from Disaster
parent_slug: knowledge-base
status: publish
---

A working backup is the difference between a bad day and a destroyed business. Hard drives fail. Laptops get stolen. Ransomware encrypts everything. A coffee spill ruins a MacBook. Every one of these happens to someone every day. With a backup, you lose a few hours of work; without one, you lose years.

This guide explains the 3-2-1 backup rule and gives you a step-by-step setup using built-in tools on Windows and Mac. Total setup time: about an hour. Cost: under $100 for the hardware.

## The 3-2-1 rule

The rule that has not aged:

- **3 copies** of any file you can't afford to lose.
- **2 different kinds of storage** (so a single failure doesn't take all copies).
- **1 copy off-site** (somewhere not in your house, in case of fire, flood, theft, or ransomware).

For most people that works out to:
- 1 copy on your computer's main drive (you have this already).
- 1 copy on a local external hard drive or NAS.
- 1 copy in cloud storage.

If you only do one new thing, do the cloud copy — it covers the most disaster cases.

## The 4 things that should be backed up

Don't try to back up everything. Most of your hard drive is the operating system and apps, which you can reinstall in an afternoon. Back up the things that can't be recreated:

1. **Documents** — Word files, PDFs, spreadsheets, contracts, tax records.
2. **Photos and videos** — anything personal or work-related.
3. **Email**, if you use Outlook or Mail with local copies (web email like Gmail is already backed up on Google's side).
4. **Anything in your `Desktop`, `Documents`, `Downloads`, `Pictures`, and `Videos` folders** — these are usually where the irreplaceable stuff lives.

## Step 1: Set up the cloud backup

This is the one to do first because it protects against the most disasters (theft, fire, ransomware) and it works in the background once configured.

**Option A: iCloud Drive (Mac and iPhone — easiest if you have Apple)**
1. System Settings → Apple ID → iCloud.
2. Turn on iCloud Drive.
3. Click "Options" next to iCloud Drive and turn on "Desktop & Documents Folders." This means anything on your desktop or in your Documents folder is automatically copied to iCloud.
4. Free tier gives you 5 GB. If you have more than that, upgrade to iCloud+ ($0.99 USD/month for 50 GB, $2.99 for 200 GB).

**Option B: Microsoft OneDrive (Windows or Mac — easiest if you use Microsoft 365)**
1. If you have a Microsoft 365 subscription, you already get 1 TB of OneDrive included.
2. Install OneDrive (built into Windows 10/11; download from microsoft.com on Mac).
3. Sign in with your Microsoft account.
4. Right-click the OneDrive icon → Settings → Backup → "Manage Backup."
5. Select Desktop, Documents, Pictures. Click "Start backup."

**Option C: Google Drive (all platforms — easiest if you use Gmail / Google Workspace)**
1. Install "Google Drive for Desktop" from drive.google.com.
2. Sign in with your Google account.
3. In Google Drive preferences, set the folders you want to sync.

**Option D: Backblaze (most thorough, $9 USD/month — for people who want everything backed up automatically)**
1. backblaze.com → sign up → install the app.
2. It backs up EVERYTHING on your computer (and any external drives) automatically. Unlimited storage.
3. No need to pick folders — it just works.

Pick one. Don't try to use multiple cloud services — it gets confusing and expensive.

## Step 2: Set up the local backup (Mac — Time Machine)

Time Machine is built into Mac and is excellent. Hardware needed: an external hard drive at least 2× the size of your internal drive. A 2 TB drive from any reputable brand (Seagate, Western Digital, LaCie) costs around $70 USD.

1. Plug the external drive into your Mac.
2. macOS will pop up: "Use this drive to back up with Time Machine?" Click "Use as Backup Disk."
3. If it doesn't ask, go to System Settings → General → Time Machine → "Add Backup Disk" and select the drive.
4. Time Machine will run the first backup (can take several hours). After that, it runs in the background every hour as long as the drive is connected.

Leave the drive connected when you're at your desk. If you're a frequent traveler, unplug and re-plug at least once a week.

## Step 2: Set up the local backup (Windows — File History or Backup and Restore)

Windows has built-in tools that work well; we recommend File History on Windows 10 and 11.

1. Plug an external hard drive into a USB port.
2. Open Settings → Update & Security → Backup → "Add a drive."
3. Pick the external drive.
4. Click "More options" and add any folders not already on the list (Desktop, Documents, Pictures, Videos, Music, Downloads).
5. Set "Back up my files" to "Every hour."
6. Click "Back up now" to run the first backup.

Same advice as Mac: leave the drive plugged in when you're at your desk.

## Step 3: Test the restore (the step everyone skips)

A backup you've never restored from is a backup you don't actually have. Once a quarter, pick one file you don't need and try to restore it.

**Mac (Time Machine):** Click the Time Machine icon in the menu bar → "Browse Time Machine Backups" → navigate to the file → click "Restore."

**Windows (File History):** Settings → Backup → "Restore files from a current backup" → search for the file → click the green restore button.

**Cloud:** Log in to icloud.com / onedrive.live.com / drive.google.com on a different device. Can you see your files? Can you download one?

If any of these don't work, you don't have a working backup. Fix it before you need it.

## Step 4: Versioning matters more than you think

A common ransomware tactic: encrypt your files, wait a few days for your backup system to copy the encrypted versions on top of the good versions, then demand ransom. By the time you notice, your "backup" only has encrypted files.

Defenses:
- **Time Machine** keeps hourly versions for 24 hours, daily versions for a month, and weekly versions until the drive is full. You can almost always find a clean version from before any infection.
- **OneDrive, Google Drive, iCloud** all keep file version history for at least 30 days. You can right-click a file → "Version history" → restore an older version.
- **Backblaze** keeps 30 days of versions on the cheapest plan; you can upgrade to one year.

Don't use a backup tool that only keeps the most-recent copy. You want to be able to go back at least 30 days.

## Special cases

### A small business with multiple computers
A NAS (network-attached storage device) like a Synology DS224+ (around $300 USD) sits on your home or office network and backs up multiple computers automatically. Combined with cloud backup, this is the small-business standard. Klaravex can set this up for you as part of the `tech-kit` or `solo-launch` SKU.

### External hard drive only — no cloud
This is BETTER than no backup, but it's not enough. If your office burns down or gets robbed, both your computer and your backup drive go together. Add a cloud copy as soon as you can.

### "But I don't have anything important to back up"
You do. Tax records, photos of family, emails from years ago, business contacts, that one PDF of the lease, scan of your passport. Think about what would hurt to lose, not what you remember off the top of your head.

## When to call for help

If you've been meaning to set up backups for months and keep putting it off, this is exactly what Klaravex's per-incident session is built for. We get you set up with cloud + local backup, test the restore, and walk you out in about an hour. The same applies for small businesses — we can put a real backup strategy in place that survives a fire, a flood, or ransomware.

If you have questions, reply to any Klaravex email or write to support@klaravex.com.
