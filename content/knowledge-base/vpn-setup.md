---
slug: vpn-setup
title: Setting Up and Troubleshooting VPN on Windows and Mac
parent_slug: knowledge-base
status: publish
---

A VPN (Virtual Private Network) creates an encrypted tunnel between your device and a remote server. Businesses use VPNs to give employees secure remote access to internal systems — file servers, internal apps, and corporate resources — without exposing those systems to the public internet.

## What a VPN Does (and Does Not Do)

A business VPN encrypts your internet traffic and routes it through your company's network, making it appear as though you are physically in the office. This is essential for:

- Accessing internal file shares and business applications from home or while traveling
- Protecting sensitive data on public WiFi (coffee shops, airports, hotels)
- Complying with security policies that require all traffic to pass through a corporate firewall

A VPN does not make you anonymous on the internet and is not a substitute for antivirus or endpoint security. Consumer VPN services (NordVPN, ExpressVPN) serve a different purpose than business VPNs — this guide focuses on business use.

## Windows Built-In VPN Client

Windows includes a built-in VPN client that works with standard protocols (IKEv2, PPTP, SSTP, and L2TP/IPsec). Your IT team will provide the server address and protocol details.

1. Open Settings → Network & Internet → VPN.
2. Click "Add a VPN connection."
3. Fill in the fields:
   - VPN provider: Windows (built-in)
   - Connection name: anything you like (e.g. "Company VPN")
   - Server name or address: provided by your IT team
   - VPN type: IKEv2 is recommended if your server supports it
   - Sign-in info: enter your username and password, or leave blank to enter at connection time
4. Click Save.
5. Click the VPN connection and choose "Connect."

## Common Business VPN Clients

Many businesses use a dedicated VPN client rather than the Windows built-in one. These require software installation:

- **Cisco AnyConnect / Cisco Secure Client:** Common in enterprise environments. Download from your company's IT portal or from Cisco's site. Enter the server address your IT team provides, then sign in with your corporate credentials.
- **Palo Alto GlobalProtect:** Similar to AnyConnect. Enter the portal address from IT, sign in with your domain credentials.
- **WireGuard:** A modern, lightweight VPN protocol increasingly used by smaller businesses. Install WireGuard from wireguard.com, then import the configuration file your IT team provides (it will be a .conf file).

**On Mac:** All three of the above have Mac versions. Cisco AnyConnect and GlobalProtect install like standard Mac apps. WireGuard is available from the Mac App Store.

## Troubleshooting Common VPN Problems

### Wrong Credentials

The most common VPN login failure is using the wrong username or password. Business VPNs typically use your corporate domain credentials — the same username and password you use to log in to your work computer. If your Windows login password changed recently, update it in the VPN client as well.

### VPN Connects but Internet Stops Working

Some business VPNs use "full tunnel" routing — all your internet traffic goes through the corporate network when the VPN is connected. If a website you normally visit is suddenly blocked, that is why. Contact your IT team to ask whether split tunneling is available (split tunneling lets local internet traffic bypass the VPN while still routing corporate traffic through it).

### DNS Leaks and "Sites Not Found"

If you can connect to the VPN but internal systems show as "not found," the VPN may not be pushing the correct DNS settings to your machine.

1. Disconnect the VPN.
2. Open Command Prompt (Windows key + R → type `cmd`) and type `ipconfig /flushdns` then press Enter.
3. Reconnect the VPN.
4. If the problem persists, your IT administrator may need to check the DNS server configuration on the VPN server.

### Split Tunneling Conflicts

If you are connected to VPN and your internet is partially working (some sites load, others do not), there may be a routing conflict. Disconnect the VPN, restart your computer, reconnect, and test again. If the problem persists, report it to your IT team with specific examples of what works and what does not.

### Certificate Errors on Connection

If you see a "certificate not trusted" error when connecting, do not proceed without checking with your IT team. This could indicate the VPN certificate expired (an IT issue) or, in rare cases, a network interception attempt.

## Klaravex Manages VPN for Business Clients

Setting up a reliable, secure VPN for a business involves more than just installing software — it requires configuring the server, managing certificates, setting up user access, and monitoring connections. Klaravex handles VPN setup and management as part of our managed security service tiers.

Still having trouble? Chat with Loki or call us at +1 (424) 348-6010. We can help troubleshoot VPN connection issues and, for business clients, manage your entire VPN infrastructure.
