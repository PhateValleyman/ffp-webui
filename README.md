# FFP WebUI 0.7.0 — Zyxel NSA320

České administrační rozhraní pro Zyxel NSA320 s FFP 0.7.0. Cílové zařízení má potvrzený Linux 2.6.31.8, ARMv5TE/armv5tel a 512 MiB RAM. Majitel ověřil Python 3.13.16 ve statické variantě `/ffp/opt/python-3.13-static/bin/python3.13`; načítá potřebné moduly včetně `math`, SSL a SHA-256 a přes něj lze spustit WebUI. Verze 0.7.0 používá stejný statický runtime, nikoli nefunkční obecný odkaz `/ffp/bin/python3.13`. Nový balík WebUI 0.7.0 na NAS zatím nainstalován nebyl.

Výchozí adresa je `http://192.168.1.20:8888`. Rozhraní je bez přihlášení a umožňuje správu jako root, jak majitel požaduje pro svou soukromou síť. Sestavení nic nekopíruje ani nemění na NASu.

## Co přináší 0.7.0

- **Rclone jako součást FFP WebUI:** aplikace najde nakonfigurované remote účty, prochází obsah, nabízí průvodce podle providerů a spouští kopírování na pozadí se stavem a průběhem. Rclone RC proces se automaticky spustí jen na `127.0.0.1`; WebUI nabízí úzké, konkrétní API pro seznamy, konfiguraci, prohlížení a kopírování, nikoli otevřený obecný RC proxy. SFTP remotes se navíc zobrazí jako samostatný zdroj a mohou sloužit pro SSH terminál. Přehled architektury a ověřené verze jsou v [`references/rclone-webui-integration-research.md`](references/rclone-webui-integration-research.md); oficiální dokumentace: [Rclone Web GUI](https://rclone.org/gui/) a [Remote Control API](https://rclone.org/rc/).
- **Dva souborové panely:** každý panel může ukazovat NAS, připojené ADB zařízení, aktivní spravovaný SSHFS mount, SFTP remote nebo jiné Rclone úložiště. K dispozici jsou hledání, řazení, výběr více položek a kopírování mezi podporovanými zdroji. Přenosy zahrnující Rclone jsou asynchronní a nemažou jiné cílové soubory; při shodě názvů může Rclone cílový soubor aktualizovat. Přímý přenos **ADB ↔ Rclone/SFTP zatím podporován není** — použijte NAS jako mezikrok. NAS/ADB archivní přenosy mohou dočasně spotřebovat místo na NASu i paměť prohlížeče.
- **Záložky souborů:** aktuální cestu lze uložit z panelu A nebo B a později otevřít v libovolném panelu. Záložky lze upravit či smazat; podporují všechny typy panelových zdrojů. Jsou uloženy v `localStorage` právě používaného prohlížeče, ne na NASu, a obsahují jen typ zdroje, cestu a identifikátor zařízení/remote — ne hesla ani tokeny.
- **Náhledy obrázků a videí:** náhledy jsou dostupné pro NAS, ADB, SSHFS, SFTP i Rclone. Nahraná data jednoho náhledu jsou omezena na 32 MiB. Video seek přes vzdálené ADB/Rclone může znovu stáhnout celý soubor v rámci tohoto limitu, proto jde o praktický prohlížeč menších médií, ne o streamování velkých filmů.
- **Terminál:** až šest přepínatelných PTY relací s ANSI barvami: NAS shell, ADB shell, SSH host a SFTP remote. Akce „Terminál zde“ startuje relaci z vybrané cesty; nové tlačítko uloží složku do stejných záložek jako souborové panely. U NAS shellu se ukládá živá pracovní cesta procesu; u ADB/SSH/SFTP se cesta před uložením nabídne k potvrzení či úpravě, protože aktuální `pwd` vzdáleného interaktivního shellu nelze bezpečně a spolehlivě zjistit. Součástí je třířadá dotyková klávesnice ve stylu dodané ukázky: F1–F10, šipky, Home/End, Ctrl, Shift, Esc, Tab a Enter. Ctrl/Shift se použijí jako jednorázové modifikátory pro další znak. ADB `.sh` lze spustit po přesném potvrzení.
- **Správa ADB:** párování, připojování a odpojování, pokročilá správa systémových i uživatelských aplikací (instalace APK, zmrazení/povolení, smazání dat a odinstalace podle možností zařízení), stažení APK i restart do podporovaných režimů. Destruktivní akce vyžadují potvrzení.
- **Služby, prostředí, Tweaks a balíčky:** správa skriptů `/ffp/start`, autostartu, skutečného prostředí root po `bash -l`, textových shell profilů a Tweaks cronu; instalované balíčky se zjišťují přes `funpkg -q .` a katalog používá dostupný `slacker`. Před změnou souborů se vytváří zálohy podle příslušné funkce.
- **Původní Zyxel WebUI:** odkazy na `/r49435`, `/adv` a `/admin`; volitelná pomocná obrazovka může předat údaje starému CGI přes HTTP URL. Heslo v URL může skončit v historii nebo logu; při potížích použijte přímý odkaz a přihlášení ve firmwaru.

## Runtime a omezení

Startovací skript používá `/ffp/bin/python3.13-static`, který odkazuje na ověřený statický Python a nastaví CA cestu. Před startem ověřuje dostupnost `math`, `hashlib` a `ssl`. Snapshot root-login prostředí používá statický interpreter přímo, aby zaznamenal skutečné hodnoty prostředí. Starý `/ffp/bin/python3.13` odkaz se nepřepisuje. Python `curses` rozšíření není pro ANSI PTY vyžadováno; Python 3.13 modul `cgi` odstranil a WebUI jej nepoužívá.

Uživatel na cílovém NASu ověřil `rclone v1.65.2-DEV`, staticky sestavené pro ARMv5 bez hard-float s Go 1.19.3; základní `rclone version` na tomto jádře běžel. Konkrétní provider, přihlášení/OAuth, každý remote a dlouhé přenosy je třeba ověřit na cílových účtech. Některé OAuth průvodce vyžadují další autentizační krok mimo formulář WebUI.

Přenosy NAS/ADB využívají bezpečné archivy a existující limity. Přímé ADB↔Rclone kopírování není součástí této verze. SSHFS terminál potřebuje rozpoznatelný `host:/cesta` zdroj v aktivním spravovaném mountu; individuální port nebo klíč nastavený pouze pro samotný mount nemusí být přenesen do terminálu, pokud není také dostupný v SSH konfiguraci. Některé Androidy nepodporují všechny režimy restartu nebo mohou vyžadovat jiný režim odemykání.

## Kontrola a sestavení

V kořeni projektu spusťte:

```sh
python3 -m py_compile ffp/ffp/bin/ffp-webui ffp/ffp/bin/ffp_webui_rclone.py
python3 -m unittest discover -s tests -v
node --check internal/webui/assets/app.js
sh -n build.sh ffp/ffp/start/ffp-webui.sh
./build.sh
```

Testy pokrývají validaci cest Rclone a velikostní limity náhledů. Sestavení vytvoří instalační archiv `dist/ffp-webui-0.7.0-python3.13-static-UNVERIFIED.txz`, zdrojový archiv `dist/ffp-webui-0.7.0-source.tgz`, SHA-256 manifest `dist/ffp-webui-0.7.0-SHA256SUMS` a rozbalený náhled `dist/stage/`. Instalační `.txz` je určen pro `funpkg`; zdrojový `.tgz` se neinstaluje. Přípona `UNVERIFIED` označuje, že tento build WebUI ještě nebyl instalován a otestován na cílovém NASu.

Před případnou ruční instalací zkontrolujte checksum a zazálohujte `/ffp/etc/ffp-webui/config.json`:

```sh
cd /cesta/k
sha256sum -c ffp-webui-0.7.0-SHA256SUMS
funpkg -i /cesta/k/ffp-webui-0.7.0-python3.13-static-UNVERIFIED.txz
# nebo pro již nainstalovaný balíček:
funpkg -u /cesta/k/ffp-webui-0.7.0-python3.13-static-UNVERIFIED.txz
/ffp/start/ffp-webui.sh restart
```

Demo běží ze stage, aby byly statické soubory ve správné cestě:

```sh
python3 dist/stage/ffp/bin/ffp-webui --config dist/stage/ffp/etc/ffp-webui/config.json --demo
```

Demo používá fiktivní data, nepřipojuje zařízení ani remote úložiště a odmítá změny.

## GitHub Releases

Po dokončení a ověření nové verze ji vydejte verzovaným tagem ve formátu `vX.Y.Z`, například:

```sh
git tag v0.8.0
git push origin v0.8.0
```

GitHub Actions po pushi tagu spustí statické kontroly, regresní testy a sestavení. Pokud vše projde, vytvoří veřejný GitHub Release s instalačním souborem `ffp-webui-X.Y.Z-python3.13-static-UNVERIFIED.txz` a kontrolním součtem SHA-256. Přípona `UNVERIFIED` zůstává, dokud daný balík není ověřen na cílovém NASu. Tagujte pouze hotovou verzi; běžný commit ani dosud nedokončená verze release nevytvoří.

## Stav ověření

Nový balík 0.7.0 nebyl na NAS nainstalován; server ani nastavení NASu tímto úkolem nebyly změněny. Ověřeno je lokální sestavení, statická kontrola Pythonu/JavaScriptu, regresní testy a lokální demo HTTP smoke test po sestavení. Po případném nasazení zbývá na cíli ověřit službu po restartu/upgrade, konkrétní Rclone provider a OAuth, přenosy s reálnými zdroji, SSHFS terminál a ADB operace.
