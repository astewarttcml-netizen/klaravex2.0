---
slug: windows-update
title: Windows Updates — What to Do When Your Computer Keeps Asking to Restart
parent_slug: knowledge-base
status: publish
---

That "restart required" notification seems to come at the worst times. But Windows updates exist for good reason — and knowing how to manage them means you can stay secure without being caught off guard.

## Why Windows Updates Matter

Windows updates are not just about new features. The majority of updates are security patches that fix vulnerabilities that hackers actively exploit. When Microsoft discovers (or is told about) a security flaw, they issue a patch. The time between a vulnerability being made public and attackers starting to exploit it is often measured in days — sometimes hours.

Keeping your computer updated is one of the most effective things you can do to protect yourself from ransomware, data theft, and account compromise. Skipping updates for months at a time leaves known security holes open.

## How to Check What Updates Are Pending

1. Open Settings (Windows key + I).
2. Go to Windows Update (Windows 11) or Update & Security → Windows Update (Windows 10).
3. Click "Check for updates" if the page has not checked recently.
4. You will see a list of pending updates. Anything labeled "Security update" or "Critical update" should be installed promptly.

If a restart is required, the page will show a "Restart now" button or let you schedule the restart for a specific time.

## Schedule the Restart for Off-Hours

You do not have to restart in the middle of your workday. Windows lets you schedule the restart for a convenient time.

1. In Windows Update, look for "Schedule the restart" or "Pick a time."
2. Choose a time when you are not using the computer — late evening or early morning works well.
3. Make sure the computer stays plugged in and awake (or set it to not sleep during updates in the Power & sleep settings).

For laptops, plug in the power adapter before scheduled update restarts — updates that run out of battery partway through can cause problems.

## When an Update Gets Stuck

Occasionally an update will stall at a percentage and not progress for an hour or more. Here is what to do:

1. Wait at least 2–3 hours before concluding it is stuck — some large updates genuinely take a long time.
2. If it is truly stuck, run the Windows Update Troubleshooter:
   - Windows 11: Settings → System → Troubleshoot → Other troubleshooters → Windows Update → Run
   - Windows 10: Settings → Update & Security → Troubleshoot → Windows Update → Run the troubleshooter
3. The troubleshooter can clear stuck update files and reset the Windows Update service.
4. After running the troubleshooter, restart your computer and try Windows Update again.

If updates continue to fail, note the error code shown (it looks like 0x80070002 or similar) and search Microsoft's support site for that specific code — each one has a documented fix.

## Quality Updates vs Feature Updates

Not all Windows updates are the same:

- **Quality updates (monthly "Patch Tuesday"):** Released on the second Tuesday of every month. These include security patches and bug fixes. They are small, install quickly, and should be applied promptly. The restart time is usually 5–15 minutes.
- **Feature updates (twice a year):** These are larger updates that add new features to Windows (like updating from Windows 11 22H2 to 23H2). They take longer to install — sometimes 30–60 minutes — and may change the look or behavior of Windows slightly. They are also important for security, as Microsoft only patches the two most recent feature update versions.

If you are on an older feature version (check Settings → System → About → Windows specifications), you may see a prompt to install a newer feature update. Plan for this during off-hours as it will take longer than a typical monthly patch.

## How Klaravex Handles Patch Management for Business Clients

For business clients, manually checking and applying updates on every computer is not practical. Klaravex uses Atera RMM (Remote Monitoring and Management) to automate patch management across all your endpoints:

- Security patches are automatically applied and tested before deployment
- Restarts are scheduled during off-hours (overnight or weekends) so employees are never interrupted
- The patch status of every device is visible in a central dashboard
- Failed updates are flagged and investigated before they become a problem

This means your business stays up to date automatically, with no action required from you or your staff.

Still having trouble with Windows updates? Chat with Loki or call us at +1 (424) 348-6010. Klaravex can remotely diagnose stuck updates, clear corrupted update files, and get your computer current again.
