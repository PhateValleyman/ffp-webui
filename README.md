# FFP WebUI 0.12.3 — Zyxel NSA320

České administrační rozhraní pro Zyxel NSA320 s FFP 0.7.0. Cílové zařízení má potvrzený Linux 2.6.31.8, ARMv5TE/armv5tel a 512 MiB RAM. Ověřený Python je 3.13.16 ve statické variantě `/ffp/opt/python-3.13-static/bin/python3.13`; právě tento runtime používá WebUI. Vydání 0.10.0 bylo instalováno, spuštěno a následně vráceno ze zálohy na cílovém NASu; nové Zypkg mutace z 0.11.0 na NASu spuštěny nebyly. Ve v0.12.0 byla na cílovém NASu read-only ověřena kompatibilita ADB snímání obrazovky; WebUI nebylo aktualizováno a dotykový ani textový vstup nebyl odeslán. Opravné v0.12.2 nastavuje výchozí Luanti `user_path` na `/ffp/home/root/.minetest`, bezpečně migruje předchozí automatickou cestu `.minetest/data` jen při standardním rozložení a zrychluje výpis modů; vlastní cesty zůstávají zachované. V0.12.3 rozšiřuje ADB mirror o fullscreen, ovládací gesta, hardwarové klávesy a best-effort ovládání klávesnice Androidu.

**Bezpečnostní upozornění:** WebUI nemá přihlášení a poskytuje správu s oprávněními root. Provozujte jej pouze v důvěryhodné soukromé síti; nevystavujte jej přímo do internetu.

## Novinky v 0.12.3

- ADB náhled lze přepnout do celoobrazovkového režimu; ovládací prvky zůstávají součástí obrazovky a prohlížeč dovoluje návrat klávesou Escape.
- Ovládání klávesnice je pouze best-effort: po klepnutí na textové pole tlačítko znovu klepne na stejné místo a požádá aplikaci o zobrazení klávesnice. Skrytí posílá **Zpět**, což může při nezobrazené klávesnici provést návrat v aplikaci; ADB neposkytuje univerzální příkaz ani spolehlivý stav její viditelnosti.
- Přibyla tlačítka pro uzamknutí/probuzení obrazovky (power key) a hlasitost nahoru/dolů. Šipky nahoru, dolů, doleva a doprava odesílají swipe gesta; **Rychlé nastavení** stáhne panel přejetím od horního okraje.
- Ovládání používá stávající omezené ADB endpointy a validované swipe souřadnice. Snímky jsou nadále načítány přímo z připojeného zařízení; nic se do Androidu neinstaluje ani neukládá.

## Novinky v 0.12.2

- Výchozí `user_path` je nyní `/ffp/home/root/.minetest`, aby Luanti sdílelo jeden očekávaný kořen s existujícími `builtin`, `games`, `worlds`, `mods`, `skins` a `data`. Dřívější výchozí `.minetest/data` se migruje pouze tehdy, když hry, světy, mody a skiny zůstávají v přímých podsložkách; při vlastních cestách se staré umístění zachová a překryvy se odmítnou.
- Výpis modů načte `world.mt` vybraného světa jednou pro celý seznam místo opakovaného čtení pro každý mod; stav `load_mod_<název>` zůstává stejný.
- Přidány regrese pro migraci staré výchozí cesty, zachování vlastní cesty, jednorázové načtení konfigurace a odmítnutí přepsání existujícího světa při vytvoření či importu.

## Novinky v 0.12.1

- Potvrzení akcí ve všech kartách používají jednotný dialog s explicitními tlačítky **Zrušit** a tlačítkem pojmenovaným podle akce, například **Smazat**, **Restartovat** nebo **Použít změny**. Upozornění, cíle i rekapitulace přenosů zůstávají viditelné; žádnou frázi není třeba opisovat.
- Dialog je ovladatelný klávesnicí; po otevření je zaměřeno Zrušit, Escape potvrzení zruší a Enter neodesílá formulář. Přesné serverové kontroly zůstávají zachované.
- Karta **ADB zařízení** nabízí živý náhled obrazovky připojeného Androidu a základní ovládání klepnutím/tažením, navigačními tlačítky Zpět/Domů/Nedávné a omezeným textovým vstupem. Nepoužívá `scrcpy`, neinstaluje aplikaci do Androidu a snímky neukládá.
- Snímek se obnovuje přibližně jednou za sekundu. Read-only test na NASu potvrdil funkčnost `adb exec-out screencap -p` s jeho ADB 1.0.32; žádný vstup do tabletu nebyl odeslán a WebUI v0.12.0 nebylo na NAS instalováno.
- WebUI nemá přihlášení; obrazovka i text odeslaný do zařízení mohou obsahovat citlivé údaje. Zrcadlení používejte pouze v důvěryhodné soukromé síti a jen na zařízení, které smíte ovládat.

## Novinky v 0.11.0

- Karta **Balíčky** nyní zobrazuje skutečné výstupy `zy-pkgs query all`, `newver`, `status`, `built-in` a `freespace`; lze se také zeptat na konkrétní balíček nebo skupinu. Výstup se zobrazuje jako text firmwaru, protože jeho přesný formát není cílově ověřen.
- Přidány potvrzované operace Zypkg **instalovat, aktualizovat, povolit, zakázat a odebrat**, plus ruční obnovení seznamu repozitáře. Backend používá pouze `zysh -e` a pevný whitelist příkazů; nevolá `zysh-cgi` ani obecný shell. Zypkg je oddělené od FFP `funpkg`/`slacker` i od automatického aktualizátoru FFP-WebUI.
- Cílové read-only příkazy jsou ověřené; žádná instalace, aktualizace, změna povolení/zakázání ani odebrání nebyly při této práci provedeny na NASu. Před první mutující operací doporučujeme nejprve zkontrolovat výstupy a ověřit chování na testovacím zařízení; závislosti ani rollback WebUI neřeší.

## Novinky v 0.10.0

- Karta **Balíčky** nyní odděluje FFP (`funpkg`/`slacker`) od nativní správy Zypkg a obsahuje odkazy na obě odpovídající stránky firmwaru Zyxel. Odkazy pouze otevřou původní WebUI; FFP-WebUI neposílá neověřené CGI příkazy a správu Zypkg nepřebírá.
- Nastavení automatických aktualizací firmwarových Zypkg balíčků se netýkají aktualizace FFP-WebUI.

## Novinky v 0.9.5

- Luanti nyní přijímá `/ffp/home/root/.minetest` jako `user_path`, když jsou hry, světy, mody a skiny přesně v jeho přímých podsložkách `games`, `worlds`, `mods` a `skins`. Jiné překryvy, vnořené cesty a symlinkové aliasy se nadále odmítají.
- Testy pokrývají podporované rozložení i zamítnutí vnořené cesty a symlinkového aliasu. NAS nebyl změněn ani použit k testování.

## Novinky v 0.9.4

- Výpis her, výběr hry pro svět a spuštění serveru nyní používají skutečné ID Luanti. ID se odvozuje ze jména složky hry; koncovka `_game` se odstraňuje (`minetest_game` → `minetest`). Starší ID se řeší přes `aliases` v `game.conf`; svévolný klíč `id` se nepovažuje za ID hry. Nejednoznačné ani chybějící hry se bezpečně odmítnou.
- Ověření zahrnulo rozložení nahlášené z NAS (`devtest`, `minetest_game` a světy s ID `minetest`, `extra_ordinance` či bez ID). NAS nebyl změněn ani použit k testování.

## Novinky v 0.9.3

- Opraven výpis kategorie modů, který vracel HTTP 500 kvůli chybějící metodě `mod_enabled`. Stav se načítá z `load_mod_<název>` v `world.mt` vybraného světa; chybějící záznam znamená vypnutý mod a bez zvoleného světa se stav nezobrazuje.

## Novinky v 0.9.2

- Luanti lze spustit pod vybraným existujícím systémovým účtem včetně `root`.
- **Uložit pouze cesty** ověřuje a ukládá jen sedm cest; nevyžaduje zvolenou hru, svět ani servisní účet. Chyba při zápisu ponechá dosavadní nastavení beze změny a běžné chyby souborového systému se zobrazí s konkrétním důvodem.

## Novinky v 0.9.1

- Luanti nyní nabízí tlačítko **Uložit pouze cesty**, které nevyžaduje vybranou hru, svět ani servisní účet. Po uložení se znovu načtou dostupné hry a světy; účet a úplnou konfiguraci lze nastavit později.
- Výchozí cesty odpovídají rozložení na NSA320: `/ffp/bin/luantiserver`, `/ffp/etc/luanti/minetest.conf` a `/ffp/home/root/.minetest/{games,worlds,mods,skins,data}`. Instalace s dosavadními automatickými cestami se převede; vlastní cesty zůstanou zachovány.
- Cesty mohou vést přes symlinkovaný domovský adresář FFP. Překryvy datových cest a aliasy na interní stav WebUI se stále odmítají; přístup servisního účtu se kontroluje na skutečném cíli.

## Novinky v 0.9.0

### Luanti server

- Nová karta spravuje jednu dedikovanou instanci: start/stop/restart, log, port, bind adresu, konfiguraci a cesty pro hry, světy, mody, skiny a uživatelská data. Konfigurace ani cesty nelze měnit za běhu; citlivé hodnoty v konfiguračním souboru zůstávají při úpravě maskované.
- Umožňuje vytvářet a vybírat světy, nastavovat jejich hru, povolovat/zakazovat mody, zobrazit bezpečně formátované `README.md` nebo historický překlep `REDADME.md`, importovat `.tar.gz`/`.tgz`/`.zip` obsah a vytvářet/stahovat zálohy `.tar.gz`. Import vyžaduje jedinou kořenovou složku, nikdy nepřepisuje existující obsah a limituje upload i rozbalení na 512 MiB a 5 000 položek.
- Karta vypisuje auth záznamy včetně offline hráčů pro SQLite3 nebo legacy `auth.txt`. Přidání vytvoří účet bez hesla s výslovným potvrzením; před veřejným spuštěním se musí heslo nastavit přímo v Luanti. Odebrání smaže jen autentizační/oprávňovací záznam a ponechá inventář i pozici k obnově. Úprava hodnot a inventářů je budoucí rozšíření.
- Luanti běží pod vybraným existujícím systémovým účtem včetně `root`; WebUI účty NASu nevytváří ani neupravuje. Staré root-owned světy lze po samostatném přesném potvrzení převést na zvolený účet. Funkce hráčů pro `auth.sqlite` vyžaduje, aby statický Python obsahoval modul `sqlite3`.
- NAS nemá v této práci ověřenou instalaci Luanti, její verzi ani sqlite3 modul statického Pythonu; dostupnost a chování serverové binárky je nutné ověřit na zařízení. Technické zdroje a tyto limity jsou v [`references/luanti-management-sources.md`](references/luanti-management-sources.md).

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
- Správa ADB, služeb a autostartu, FFP prostředí a balíčků (`funpkg`/`slacker`), Zypkg přes oddělený správce firmwaru, root shell profilů, Tweaks cronu a původního Zyxel WebUI.
- ADB zrcadlení Androidu s dotykovým klepnutím/tahem, Zpět/Domů/Nedávné a textovým vstupem; snímky se získávají přes existující `adb exec-out screencap` (bez `scrcpy`, instalace balíčků nebo ukládání snímků).
- Správa Luanti serveru, jeho světů/her/modů, archivů a auth záznamů hráčů včetně offline účtů (zavedeno v 0.9.0; cesty opraveny v 0.9.1; účet root povolen v 0.9.2; výpis modů opraven v 0.9.3; mapování ID her opraveno v 0.9.4; root uživatelská cesta povolena v 0.9.5).

## Runtime a limity

Startovací skript používá `/ffp/bin/python3.13-static`, který odkazuje na ověřený statický Python a nastavuje CA cestu. Před startem ověřuje `math`, `hashlib` a `ssl`. Snapshot prostředí root loginu volá statický interpreter přímo. Obecný `/ffp/bin/python3.13` se nepřepisuje. Python `curses` není pro ANSI PTY nutný; Python 3.13 odstranil `cgi` a WebUI jej nepoužívá.

Změna konfigurace remote je blokována během aktivního Rclone přenosu a během jiného nedokončeného průvodce. Rclone konfigurace obsahuje přístupové údaje; export/úprava je proto omezena na provider pole a citlivé hodnoty se nezobrazují.

Zrcadlení ADB vyžaduje na NASu existující klientský `adb` s podporou `exec-out` a zařízení ve stavu `device`. Zachycení je omezeno na 12 sekund, 16 MiB a zhruba jeden snímek za sekundu; dotykové příkazy jsou pevně omezené a textový vstup nejvýše 256 znaků. WebUI je v tomto nasazení bez přihlášení, proto jej ponechte pouze na důvěryhodné privátní LAN: obrazovka i odeslaný text mohou obsahovat citlivé údaje.

## Kontrola aktualizací

Aktualizátor se týká **pouze FFP-WebUI**, nikoli Zypkg ani jiných FFP balíčků. Při startu a potom jednou za 24 hodin zkontroluje stabilní vydání v [GitHub Releases](https://github.com/PhateValleyman/ffp-webui/releases). Pokud je NAS online a existuje novější vydání se správně pojmenovaným `.txz` a platným SHA-256 digestem od GitHubu, automaticky ho stáhne do `/ffp/var/ffp-webui/packages/`; před uložením ověří digest, velikost, HTTPS host a přesměrování. Nevyžaduje GitHub účet ani token. Pokud je NAS offline nebo kontrola selže, zůstane dostupný ruční přenos popsaný níže.

Stažený instalátor se **nikdy sám nenainstaluje**. V kartě **Balíčky → Aktualizace FFP-WebUI** lze z prohlížeče otevřít poznámky k vydání a po kontrole ručně spustit aktualizaci; WebUI vyžádá přesný potvrzovací text, předá ověřený archiv FFP správci a po instalaci ověří jeho přesný název v `funpkg -q .`. WebUI samo nevytváří zálohu ani automatický rollback. Před potvrzením zálohujte payload podle záznamů `/ffp/funpkg/installed/ffp-webui-*`, celý adresář `/ffp/etc/ffp-webui/` i příslušné záznamy balíčků. Po dokončení restartujte službu FFP-WebUI, aby načetla nové soubory. První přechod z v0.9.5 na v0.10.0 je nutné přenést ručně — v0.9.5 ještě aktualizátor neobsahuje. Další vydání může v0.10.0 stáhnout automaticky, pokud NAS získá přístup k internetu.

## Build a lokální testy

```sh
python3 -m py_compile ffp/ffp/bin/ffp-webui ffp/ffp/bin/ffp_webui_rclone.py ffp/ffp/bin/ffp_webui_luanti.py ffp/ffp/bin/ffp_webui_update.py
python3 -m unittest discover -s tests -v
go test ./...
node --check internal/webui/assets/app.js
sh -n build.sh ffp/ffp/start/ffp-webui.sh
./build.sh
```

Build vytvoří `dist/ffp-webui-0.12.3-python3.13-static-UNVERIFIED.txz` pro `funpkg`, zdrojový archiv `dist/ffp-webui-0.12.3-source.tgz`, SHA-256 manifest `dist/ffp-webui-0.12.3-SHA256SUMS` a rozbalenou ukázku `dist/stage-0.12.3/`. Přípona `.tgz` je jen pro zdroje; FFP instalátor je `.txz`.

Ruční instalace je určena pro offline NAS nebo jako záložní postup. Na počítači s internetem stáhněte z [vydání 0.12.3](https://github.com/PhateValleyman/ffp-webui/releases/tag/v0.12.3) README, instalátor `ffp-webui-0.12.3-python3.13-static-UNVERIFIED.txz`, zdrojový archiv `ffp-webui-0.12.3-source.tgz` a manifest `ffp-webui-0.12.3-SHA256SUMS`; přeneste je ručně do stejné složky na NAS. Pak ověřte kontrolní součty a nainstalujte:

```sh
cd /cesta/k/prenesenym-souborum
sha256sum -c ffp-webui-0.12.3-SHA256SUMS
funpkg -i ./ffp-webui-0.12.3-python3.13-static-UNVERIFIED.txz
/ffp/start/ffp-webui.sh restart
```

Manifest kontroluje instalátor i zdrojový archiv, proto přeneste oba. Před instalací vytvořte zálohu všech souborů vyjmenovaných v aktuálním záznamu `/ffp/funpkg/installed/ffp-webui-*`, všech souborů v `/ffp/etc/ffp-webui/` a odpovídajících záznamů balíčků; WebUI zálohu ani rollback automaticky neprovádí. Po restartu se předchozí automatická cesta `.minetest/data` přemigruje na `/ffp/home/root/.minetest` jen tehdy, když hry, světy, mody a skiny zůstávají v přímých podsložkách; vlastní cesty jsou zachované. V kartě Luanti ověřte `user_path` i ostatní cesty před startem. Změna nastavení žádné existující světy nepřesouvá ani nemaže.

Na cílovém NASu bylo ověřeno, že `funpkg -u <nový-archiv>` vrací „Not installed“ i při instalované starší verzi (a přitom může skončit návratovým kódem 0). Pro novou verzi proto použijte `funpkg -i`; NAS tím vytvoří další záznam verze a starší záznamy ponechá. Aktualizátor ve WebUI používá `-i` a kontroluje následný výpis `funpkg -q .`, aby se falešný úspěch nezobrazil jako dokončená instalace.

Demo běží ze stage a používá pouze fiktivní data:

```sh
python3 dist/stage-0.12.3/ffp/bin/ffp-webui --config dist/stage-0.12.3/ffp/etc/ffp-webui/config.json --demo
```

## Stav ověření

Verze 0.12.3 prošla 133 Python testy, Go testy, kontrolami syntaxe Pythonu/JavaScriptu/shellu a sestavením s kontrolou SHA-256. Na NSA320 `/api/health` vrátil 200 s verzí `0.12.3`; běžící backend a ADB/HTML/CSS soubory odpovídaly připravenému balíčku. Přes WebUI ADB mirroru na SHIELD Tablet `192.168.1.12:5555` byl pořízen platný PNG snímek 1200×1920. Akce hlasitosti dolů/nahoru a gesta stažení Rychlého nastavení i návratu byla přijata; hlasitost reproduktoru zůstala na 8/15 a po návratu byl v popředí Termux. V živém testu nebyly odeslány klepnutí, text, Zpět ani Power; ovládání klávesnice je best-effort.

Pro v0.12.1 prošlo 127 Python testů, Go testy, kontroly syntaxe Pythonu/JavaScriptu/shellu, build a SHA-256 ověření. Chromium ověřilo dialogy, klávesové ovládání a mobilní šířku nad skutečnými frontendovými soubory ze staged balíku, podávanými lokálním statickým HTTP serverem. Celý demo backend nebylo možné znovu spustit: demo režim má pevný localhost port 8888, který obsazoval již běžící lokální proces; tento proces zůstal nedotčen. Na NSA320 s ADB 1.0.32 byl bez zápisu do Androidu úspěšně získán platný PNG snímek přes `exec-out screencap -p`. Nebyla testována interakce s dotykem/textem a WebUI v0.12.0 nebylo na NAS instalováno. Dřívější read-only `zy-pkgs query` příkazy na NSA320 byly ověřeny; během vývoje v0.11.0 nebyla spuštěna žádná Zypkg instalace, aktualizace, změna stavu ani odebrání. Historický test v0.10.0 instaloval pouze FFP-WebUI, potvrdil health endpoint a po ověřené záloze vrátil NAS na v0.9.4; původní konfigurace zůstaly zachované. Živý aktualizátor dříve načetl GitHub Releases API a ověřil SHA-256 staženého v0.9.5 bez instalace. Před spuštěním Luanti ověřte kompatibilní serverovou binárku, modul `sqlite3` statického Pythonu a přístup ke zvoleným cestám.
