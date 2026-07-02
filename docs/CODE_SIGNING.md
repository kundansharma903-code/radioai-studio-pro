# Code Signing — SmartScreen "Unknown Publisher" fix

## Status
The installer is UNSIGNED. Windows SmartScreen shows "Unknown
Publisher" on every fresh machine. Signing requires a certificate
that must be **purchased** (identity verification by a CA — this is
the one step no code change can do).

## Options (2026 prices, approximate)

| Option | Cost | SmartScreen reputation |
|---|---|---|
| **Azure Trusted Signing** (recommended) | ~$9.99/month | Instant good reputation (Microsoft-managed certs) |
| OV code-signing cert (Sectigo/Certum via resellers like SignMyCode/CheapSSL) | ~$80-250/year | Reputation builds over downloads (days-weeks of warnings first) |
| EV code-signing cert | ~$250-400/year | Instant reputation, requires hardware token/HSM |

For MonoLoop Productions (sole proprietor), Certum's "Open Source /
individual" OV cert or Azure Trusted Signing are the practical picks.
Azure needs an Azure account + identity validation (India-supported).

## Once a certificate exists

1. Install the cert (PFX) or set up Azure Trusted Signing + `signtool`.
2. Sign the app exe AFTER PyInstaller, BEFORE Inno Setup:
   ```
   signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
     /f MonoLoop.pfx /p <password> "dist\RadioAI Studio Pro\RadioAI Studio Pro.exe"
   ```
3. Tell Inno Setup to sign the installer — add to RadioAI_Setup.iss `[Setup]`:
   ```
   SignTool=mysign
   ```
   and define the tool once in the Inno IDE (Tools → Configure Sign
   Tools) as:
   ```
   mysign=signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f C:\certs\MonoLoop.pfx /p $p $f
   ```
4. Rebuild: `ISCC.exe RadioAI_Setup.iss` — the produced setup exe is
   then signed and SmartScreen shows "MonoLoop Productions".

## Action needed from the operator
Buy one of the options above (Azure Trusted Signing recommended for
cost + instant reputation), then ask Claude to wire the signing step
into the build with the actual cert details.
