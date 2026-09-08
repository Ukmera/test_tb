# 🌐 Accès Distant Gratuit au Dashboard (Mobile / Tablette / Extérieur)

Vous pouvez visualiser et contrôler votre terminal de trading **GPTHEIST DESK** en direct depuis votre smartphone ou n'importe quel ordinateur à l'extérieur sans ouvrir de ports sur votre box internet et à **0€ (100% gratuit)**.

---

## Méthode 1 (Recommandée & Instantanée) : Cloudflare Tunnel (Gratuit, Aucun compte requis)

Cloudflare propose des **Quick Tunnels** éphémères sécurisés en HTTPS :

1. **Ouvrez un terminal PowerShell** sur votre machine.
2. Si vous n'avez pas encore `cloudflared`, installez-le en une commande :
   ```powershell
   winget install --id Cloudflare.cloudflared
   ```
   *(Ou téléchargez simplement l'exécutable portable `cloudflared.exe` depuis [GitHub Cloudflare](https://github.com/cloudflare/cloudflared/releases)).*

3. Lancez le tunnel pointant vers le dashboard :
   ```powershell
   cloudflared tunnel --url http://127.0.0.1:8088
   ```

4. **Résultat immédiat** : Cloudflare vous affiche une URL sécurisée de type :
   ```
   https://random-words-here.trycloudflare.com
   ```
   Ouvrez ce lien sur votre téléphone : vous avez le graphique en direct, les 10 agents et le playback où que vous soyez !

---

## Méthode 2 : Via Node.js / npx Localtunnel (Aucune installation requise si Node est présent)

Si Node.js est installé sur votre ordinateur :
```bash
npx localtunnel --port 8088
```
Vous recevrez immédiatement une URL publique HTTPS accessible partout.

---

## Méthode 3 : Accès au sein de votre réseau Wi-Fi local (Sans aucun outil externe)

Si vous êtes connecté au même réseau Wi-Fi que votre ordinateur :
1. Dans un terminal, tapez `ipconfig` pour trouver votre adresse IP locale (ex: `192.168.1.45`).
2. Sur votre téléphone connecté au même Wi-Fi, ouvrez simplement :
   ```
   http://192.168.1.45:8088
   ```
   *(Pensez à autoriser Python dans le pare-feu Windows si demandé).*
