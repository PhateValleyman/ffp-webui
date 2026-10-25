# FFP WebUI 0.9.0 — Zyxel NSA320

České administrační rozhraní pro Zyxel NSA320 s FFP 0.7.0. Cílové zařízení má potvrzený Linux 2.6.31.8, ARMv5TE/armv5tel a 512 MiB RAM. Ověřený Python je 3.13.16 ve statické variantě `/ffp/opt/python-3.13-static/bin/python3.13`; právě tento runtime používá WebUI. Balík 0.9.0 nebyl nainstalován ani otestován na NAS.

**Bezpečnostní upozornění:** WebUI nemá přihlášení a poskytuje správu s oprávněními root. Provozujte jej pouze v důvěryhodné soukromé síti; nevystavujte jej přímo do internetu.

## Novinky v 0.9.0

### Luanti server

- Nová karta spravuje jednu dedikovanou instanci: start/stop/restart, log, port, bind adresu, konfiguraci a cesty pro hry, světy, mody, skiny a uživatelská data. Konfigurace ani cesty nelze měnit za běhu; citlivé hodnoty v konfiguračním souboru zůstávají při úpravě maskované.
- Umožňuje vytvářet a vybírat světy, nastavovat jejich hru, povolovat/zakazovat mody, zobrazit bezpečně formátované `README.md` nebo historický překlep `REDADME.md`, importovat `.tar.gz`/`.tgz`/`.zip` obsah a vytvářet/stahovat zálohy `.tar.gz`. Import vyžaduje jedinou kořenovou složku, nikdy nepřepisuje existující obsah a limituje upload i rozbalení na 512 MiB a 5 000 položek.
- Karta vypisuje auth záznamy včetně offline hráčů pro SQLite3 nebo legacy `auth.txt`. Přidání vytvoří účet bez hesla s výslovným potvrzením; před veřejným spuštěním se musí heslo nastavit přímo v Luanti. Odebrání smaže jen autentizační/oprávňovací záznam a ponechá inventář i pozici k obnově. Úprava hodnot a inventářů je budoucí rozšíření.
- Hry a mody mohou spouštět kód. Proto server nikdy neběží jako root: vyžaduje již existující ne-root účet mimo root skupinu. WebUI účty NASu nevytváří ani neupravuje. Staré root-owned světy lze po samostatném přesném potvrzení převést na zvolený účet. Funkce hráčů pro `auth.sqlite` vyžaduje, aby statický Python obsahoval modul `sqlite3`.
- NAS nemá v této práci ověřenou instalaci Luanti, její verzi, sqlite3 modul statického Pythonu ani vhodný ne-root účet; start může vyžadovat jejich samostatné nastavení. Technické zdroje a tyto limity jsou v [`references/luanti-management-sources.md`](references/luanti-management-sources.md).

## Novinky v 0.8.0

### Rclone remote správa a OAuth

- Přidávání, úprava a odebrání nakonfigurovaných remote úložišť podle seznamu providerů Rclone. Typ již existujícího remote se nemění; pro jiný typ založte nový remote.
- Při úpravě se uložená hesla a tokeny nikdy nevracejí do prohlížeče. Prázdné citlivé pole ponechá dosavadní hodnotu, nová hodnota ji nahradí a zvláštní checkbox nastaví hodnotu na prázdný řetězec. To odstraní tajný obsah, ale ne klíč konfigurace: cílový Rclone 1.65.2 nemá novější `config/unset`, které umí klíč odebrat celý. Odebrání maže pouze konfiguraci remote, nikoli data v cloudu.
- Průvodce pokračuje přes nativní neinteraktivní otázky Rclone. Nové OAuth status/stop metody se zjišťují za běhu. Pokud je Rclone nemá, průvodce nabídne headless postup `rclone authorize "<provider>"` na počítači s prohlížečem.
- OAuth callback na `127.0.0.1` se nedá otevřít jako běžný odkaz z jiného zařízení, protože loopback pak označuje klienta, ne NAS. UI proto zobrazí URL a doporučí SSH tunel nebo [oficiální headless postup Rclone](https://rclone.org/remote_setup/).
- Rclone Remote Control proces běží pouze na `127.0.0.1`; WebUI nevystavuje obecný RC proxy. Oficiální rozhraní: [Rclone RC](https://rclone.org/rc/).

Cílový NAS má podle vlastníka `rclone v1.65.2-DEV`, staticky sestavené pro ARMv5 bez hard-float s Go 1.19.3. `rclone version` na jeho Linuxu 2.6.31.8 běžel. Novější OAuth status/stop metody se proto nepředpokládají: aplikace je feature-detectuje a použije fallback. Skutečné přihlášení, každý provider a dlouhé přenosy je nutné ověřit na NASu a cílovém účtu.

### Oprava chyb API tras

Backend nyní vrací verzi přes `/api/health`; statické soubory se načítají bez browser cache; při chybě 405 odpověď obsahuje požadovanou HTTP metodu, cestu a verzi serveru. WebUI zároveň zobrazí varování, pokud statická část a běžící backend pocházejí z různých vydání. To diagnostikuje a předchází chybám „Method not allowed or route not found“, jako na dodaném snímku: pravděpodobnou příčinou je starý běžící backend po výměně frontendových souborů.

Pokud se zobrazí varování o nesouladu verzí, po instalaci restartujte službu a znovu načtěte stránku:

```sh
/ffp/start/ffp-webui.sh restart
```

## Zahrnuté funkce

- Dva souborové panely pro NAS, ADB, aktivní SSHFS mounty, SFTP a ostatní Rclone remotes; hledání, řazení, vícenásobný výběr a podporované kopírování.
- Rclone kopírování na pozadí se stavem. Přímé ADB↔Rclone kopírování není podporováno; použijte NAS jako mezikrok. Přenosy mohou u velkých stromů vyžadovat dočasné místo.
- Záložky cest uložené v `localStorage` aktuálního prohlížeče, náhled obrázků/videí do 32 MiB a až šest přepínatelných ANSI PTY relací (NAS, ADB, SSH/SFTP).
- Správa ADB, služeb a autostartu, FFP prostředí, balíčků, root shell profilů, Tweaks cronu a původního Zyxel WebUI.
- Správa Luanti serveru, jeho světů/her/modů, archivů a auth záznamů hráčů včetně offline účtů (vydání 0.9.0; viz bezpečnostní omezení výše).

## Runtime a limity

Startovací skript používá `/ffp/bin/python3.13-static`, který odkazuje na ověřený statický Python a nastavuje CA cestu. Před startem ověřuje `math`, `hashlib` a `ssl`. Snapshot prostředí root loginu volá statický interpreter přímo. Obecný `/ffp/bin/python3.13` se nepřepisuje. Python `curses` není pro ANSI PTY nutný; Python 3.13 odstranil `cgi` a WebUI jej nepoužívá.

Změna konfigurace remote je blokována během aktivního Rclone přenosu a během jiného nedokončeného průvodce. Rclone konfigurace obsahuje přístupové údaje; export/úprava je proto omezena na provider pole a citlivé hodnoty se nezobrazují.

## Kontrola aktualizací

Automatická kontrola ani instalace nových verzí zatím není zapnutá. Veřejný zdrojový repozitář je [PhateValleyman/ffp-webui](https://github.com/PhateValleyman/ffp-webui) a vydání jsou na [GitHub Releases](https://github.com/PhateValleyman/ffp-webui/releases); verze 0.9.0 je předběžné vydání, dokud nebude instalační balík ověřen na NAS. Případná read-only kontrola má vybírat jen stabilní vydání a ověřovat SHA-256. Jedním klikem instalovat root balík by mělo přijít až po samostatném návrhu rollbacku/updateru: updater musí zastavit službu, zazálohovat celý payload i konfiguraci, použít `funpkg`, zkontrolovat lokální health a při chybě obnovit předchozí payload. Návrh je v [`references/next-release-design-notes.md`](references/next-release-design-notes.md).

## Build a lokální testy

```sh
python3 -m py_compile ffp/ffp/bin/ffp-webui ffp/ffp/bin/ffp_webui_rclone.py ffp/ffp/bin/ffp_webui_luanti.py
python3 -m unittest discover -s tests -v
node --check internal/webui/assets/app.js
sh -n build.sh ffp/ffp/start/ffp-webui.sh
./build.sh
```

Build vytvoří `dist/ffp-webui-0.9.0-python3.13-static-UNVERIFIED.txz` pro `funpkg`, zdrojový archiv `dist/ffp-webui-0.9.0-source.tgz`, SHA-256 manifest `dist/ffp-webui-0.9.0-SHA256SUMS` a rozbalenou ukázku `dist/stage/`. Přípona `.tgz` je jen pro zdroje; FFP instalátor je `.txz`.

Před případnou ruční instalací zkontrolujte checksum a zazálohujte konfiguraci:

```sh
cd /cesta/k/dist
sha256sum -c ffp-webui-0.9.0-SHA256SUMS
funpkg -i ./ffp-webui-0.9.0-python3.13-static-UNVERIFIED.txz
/ffp/start/ffp-webui.sh restart
```

Pro aktualizaci existující instalace nepoužívejte `funpkg -u`, dokud není na tomto NASu potvrzená jeho přesná sémantika a postup zálohy/obnovy konfigurace.

Demo běží ze stage a používá pouze fiktivní data:

```sh
python3 dist/stage/ffp/bin/ffp-webui --config dist/stage/ffp/etc/ffp-webui/config.json --demo
```

## Stav ověření

Sestavení, syntaxe a regresní testy se ověřují lokálně, stejně jako HTTP smoke test stage buildu. Vydání 0.9.0 a jeho instalační balík nebyly nainstalovány ani spuštěny na NAS; NAS nebyl tímto úkolem změněn. Před nasazením Luanti ověřte na zařízení dostupnost kompatibilní serverové binárky, `sqlite3` modul statického Pythonu, ne-root účtu a přístup k nastaveným cestám. Veřejný repozitář a release endpoint jsou dostupné na výše uvedených odkazech.
