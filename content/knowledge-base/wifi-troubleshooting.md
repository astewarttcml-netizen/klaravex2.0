---
slug: wifi-troubleshooting
title: WiFi Not Working? Common Fixes for Windows and Mac
parent_slug: knowledge-base
status: publish
---

Whether your WiFi suddenly dropped or your laptop refuses to connect to the wireless network, most WiFi problems can be fixed in a few minutes with the right steps. This guide walks you through the most common fixes for both Windows and Mac.

## Step 1: Isolate the Problem

Before touching any settings, check whether the issue is with your device or your internet connection itself.

- **Check other devices.** Can your phone or another computer connect to the same WiFi network? If yes, the problem is with your specific device, not the router or internet service.
- **Check the router lights.** Most routers have indicator lights. A solid or blinking internet/WAN light usually means the connection is active. If it is off or red, the issue is with your internet service provider (ISP).
- **Test with a cable.** If you have an Ethernet cable, plug it in directly. If the wired connection works but WiFi does not, the issue is wireless-specific.

## Step 2: Restart Your Router and Computer

This fixes the majority of WiFi issues and should always be the first thing you try.

1. Unplug your router (and modem, if separate) from the wall outlet.
2. Wait 30 seconds — this clears the router's memory and forces it to re-establish a fresh connection.
3. Plug the router back in and wait 60–90 seconds for it to fully restart.
4. Restart your computer as well.
5. Try connecting again.

## Step 3: Forget the Network and Reconnect

Sometimes the stored WiFi password or connection settings get corrupted. Removing the network and reconnecting fresh often resolves this.

**On Windows:**
1. Open Settings → Network & Internet → Wi-Fi.
2. Click "Manage known networks."
3. Find your network, click it, and select "Forget."
4. Reconnect by selecting the network from the taskbar WiFi list and entering your password.

**On Mac:**
1. Open System Settings (or System Preferences on older macOS) → Wi-Fi.
2. Click the network name and choose "Forget This Network."
3. Reconnect from the WiFi menu in the menu bar.

## Step 4: Run the Windows Network Troubleshooter

Windows has a built-in tool that can automatically detect and fix many common wireless issues.

1. Right-click the WiFi icon in the taskbar (bottom-right corner).
2. Select "Troubleshoot problems."
3. Follow the on-screen steps. The troubleshooter checks for driver issues, IP configuration problems, and connectivity faults.

On Windows 11, you can also go to Settings → System → Troubleshoot → Other troubleshooters → Internet Connections.

## Step 5: Update Your Network Adapter Driver

An outdated or corrupted wireless driver is a common cause of WiFi drops and connection failures, especially after a Windows update.

1. Right-click the Start button and choose "Device Manager."
2. Expand "Network adapters."
3. Right-click your wireless adapter (it usually has "WiFi" or "Wireless" in the name) and select "Update driver."
4. Choose "Search automatically for drivers."
5. Restart your computer after the update completes.

Alternatively, visit your computer manufacturer's support site (Dell, HP, Lenovo, etc.) and download the latest wireless driver for your specific model.

## Step 6: Fix an IP Address Conflict

If your computer connects to WiFi but shows "No Internet" or limited connectivity, an IP address conflict may be the cause.

1. Press Windows key + R, type `cmd`, and press Enter.
2. Type `ipconfig /release` and press Enter.
3. Then type `ipconfig /renew` and press Enter.
4. Wait a moment and try loading a website.

On Mac, go to System Settings → Wi-Fi → Details (next to your network) → TCP/IP → click "Renew DHCP Lease."

## When to Call Support

If you have tried all the steps above and still cannot connect, the issue may be:

- A hardware fault in your wireless adapter
- A router or modem that needs replacement
- An ISP outage in your area (check your provider's outage page or call them)
- A network configuration problem that requires admin access to the router

Still having trouble? Chat with Loki or call us at +1 (424) 348-6010. Klaravex can remotely diagnose WiFi and network issues for both home and business clients.
