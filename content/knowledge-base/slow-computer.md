---
slug: slow-computer
title: Computer Running Slow? How to Speed It Up
parent_slug: knowledge-base
status: publish
---

A slow computer is one of the most common IT complaints, and in most cases the fix is straightforward. Before assuming your computer is too old or needs replacing, work through these steps — you may be surprised how much performance you can recover.

## Step 1: Check What Is Using Your CPU and RAM

Task Manager tells you exactly which programs are eating up resources right now.

1. Press Ctrl + Shift + Esc to open Task Manager (or right-click the taskbar and choose "Task Manager").
2. Click the "Processes" tab.
3. Click the "CPU" column header to sort by CPU usage, highest first. Look for anything using 20% or more of your CPU consistently.
4. Click the "Memory" column to sort by RAM usage. If your total memory usage is above 80–90%, that is causing slowdowns.

Common culprits: browser tabs (Chrome is notorious for RAM usage), antivirus scans running in the background, Windows Update downloading in the background, or a program that has crashed and is stuck in a loop. You can right-click a process and choose "End Task" to stop it — just make sure you know what it is first.

## Step 2: Disable Startup Programs

Many programs add themselves to startup and run silently in the background every time you boot. Removing them from startup speeds up boot times and reduces background resource use.

1. Open Task Manager (Ctrl + Shift + Esc) and click the "Startup" tab.
2. Look for programs with "High" startup impact and that you do not need running immediately.
3. Right-click them and choose "Disable." This does not uninstall the program — it just stops it from launching automatically.

Typical startup programs you can safely disable: Spotify, Discord, Teams (if not required at login), OneDrive, Zoom, and various hardware utilities.

## Step 3: Clear Temporary Files

Windows accumulates large amounts of temporary files from updates, installations, and normal use. Clearing them frees up disk space and can improve performance.

**Quick method:**
1. Press Windows key + R, type `%temp%`, and press Enter.
2. Press Ctrl + A to select all files, then press Delete. Skip any files that say they are in use.

**Disk Cleanup (more thorough):**
1. Press Windows key + S and search for "Disk Cleanup."
2. Select your C: drive and click OK.
3. Check the boxes for Temporary files, Recycle Bin, and Thumbnails.
4. Click "Clean up system files" for additional options including old Windows Update files.
5. Click OK and confirm.

## Step 4: Check Available Disk Space

When your hard drive or SSD is nearly full, Windows cannot create the temporary space it needs to run efficiently. Performance degrades noticeably when the drive is below 10–15% free.

1. Open File Explorer and right-click your C: drive.
2. Choose "Properties" to see how much space is free.
3. If you are below 15% free, delete large files you no longer need, empty the Recycle Bin, or move files to an external drive or cloud storage (OneDrive, Google Drive).

## Step 5: Run a Malware Scan

Malware — including viruses, adware, and cryptomining software — can silently consume your CPU and slow your computer to a crawl without any obvious warning signs.

1. Open Windows Security (search for it in the Start menu).
2. Click "Virus & threat protection."
3. Click "Quick scan." If that comes back clean but the computer is still slow, run a "Full scan" — it takes longer but checks every file.

For a second opinion, download Malwarebytes Free (malwarebytes.com) and run a scan alongside Windows Security.

## Step 6: Install Pending Windows Updates That Require a Restart

Windows sometimes holds updates in a partially installed state, waiting for a restart. This can cause the system to run slower and the update process itself to consume CPU and disk activity in the background.

1. Go to Settings → Windows Update.
2. If you see "Restart required," restart your computer as soon as practical.
3. After the restart, check Windows Update again and install any remaining updates.

## Step 7: When a Hardware Upgrade Is the Answer

Software fixes have limits. If your computer is 5 or more years old and still slow after all the steps above, the hardware may be the bottleneck.

- **Under 8 GB of RAM:** Adding more RAM is one of the most cost-effective upgrades available, especially if Task Manager shows memory usage consistently above 80%.
- **Hard disk drive (HDD) instead of SSD:** If your computer has a traditional spinning hard drive (not a solid-state drive), upgrading to an SSD is the single biggest speed improvement you can make. Boot times go from 2–3 minutes to under 30 seconds.
- **CPU age:** A processor from 2014 or earlier may simply not be fast enough for modern software requirements. At that point, a new computer is likely more cost-effective than repair.

Still having trouble? Chat with Loki or call us at +1 (424) 348-6010. Klaravex can remotely diagnose slow computer issues and advise whether a tune-up, upgrade, or replacement is the right call for your situation.
