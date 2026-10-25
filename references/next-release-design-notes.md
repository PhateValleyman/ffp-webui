# Poznámky k FFP WebUI: Rclone OAuth a aktualizace

## Rclone remote správa a OAuth

Cílový NAS má podle vlastníka `rclone v1.65.2-DEV`, staticky linkované pro ARMv5 bez hard-float, s Go 1.19.3; příkaz `rclone version` na Linuxu 2.6.31.8 běžel. Nové RC metody se proto musí zjišťovat schopnostním testem, nikoli předpokládat podle aktuální dokumentace.

Oficiální [RC dokumentace](https://rclone.org/rc/) popisuje `config/create`, `config/update`, `config/delete`, `config/providers`, `config/get`, `config/oauthstatus` a `config/oauthstop`. Novější OAuth status/stop rozhraní a URL `authUrl` jsou uvedeny v [Rclone v1.75.0 changelogu](https://rclone.org/changelog/); nelze předpokládat, že je cílová v1.65.2 implementuje. Bridge má tyto metody feature-detectovat a zůstat použitelný bez nich.

Pro headless NAS oficiální [Rclone Remote Setup](https://rclone.org/remote_setup/) doporučuje odpovědět „No“ na otázku místního browseru, provést `rclone authorize "<provider>"` na počítači s prohlížečem (ideálně se stejnou verzí Rclone) a vložit vrácený token do config otázky. Alternativou je SSH tunel `localhost:53682`; loopback callback URL z NASu se nedá bezpečně otevřít jako běžný odkaz z jiného zařízení, protože `127.0.0.1` by pak znamenalo klienta. UI nesmí předstírat, že samotné `authUrl` zpřístupní callback.

Při editaci se nesmí raw `config/get` posílat do browseru: OAuth tokeny, hesla a citlivá pole zůstanou na serveru. V UI se zobrazí pouze běžné, bezpečné hodnoty a informace, že citlivá hodnota existuje; prázdné pole při editaci znamená „ponechat“, nová hodnota znamená „nahradit“. Výslovné „vymazat hodnotu“ posílá prázdný řetězec přes `config/update`, čímž se tajný obsah vymaže, ale volba zůstane v konfiguraci jako prázdná. Oficiální [config/unset dokumentace](https://rclone.org/commands/rclone_config_unset/) rozlišuje prázdný řetězec od odstranění klíče; `config/unset` přibyl až po cílové v1.65.2, takže jej zatím nepoužíváme. Smazání remote musí být samostatná potvrzená akce `config/delete`; nemaže data vzdáleného úložiště.

## Kontrola aktualizací a self-update

Veřejné [GitHub Releases REST API](https://docs.github.com/en/rest/releases/releases) poskytuje pro veřejný repozitář tag, příznaky `prerelease`/`draft`, assets, download URL a asset digest SHA-256. Release `latest` nemusí mít nejvyšší semver, proto klient porovnává parsovaný stabilní tag s lokální verzí a ignoruje prerelease/draft. Konkrétní veřejná metadata v0.9.5 jsou zaznamenána v [poznámce k release API](github-release-update-research.md).

### Chování v0.10.0

FFP-WebUI při startu a poté jednou za 24 hodin kontroluje pouze stabilní vydání `PhateValleyman/ffp-webui`. Pokud je NAS online, automaticky stáhne výhradně přesně pojmenovaný FFP-WebUI `.txz` s platným GitHub SHA-256 digestem do persistovaného stagingu. Kontrola omezuje velikost a povolené HTTPS hosty/přesměrování. Nevyžaduje GitHub účet ani token a nezasahuje do Zypkg, FFP katalogu ani jiných balíčků. Cílový NAS během testu úspěšně načetl GitHub Releases API; samostatný download-only test se simulovanou lokální v0.9.4 stáhl v0.9.5, ověřil digest a nic neinstaloval.

Stahování nikdy samo nespustí instalaci. Ruční instalaci spouští až uživatel v prohlížeči po přesném potvrzení názvu ověřeného archivu. NASové zkoušky v izolovaném `funpkg -C` rootu ukázaly, že `funpkg -u <nový-archiv>` vrací „Not installed“ i při existující starší verzi a může přesto skončit návratovým kódem 0. Pro nové celé jméno balíčku se proto používá `funpkg -i`; WebUI potom ověří, že přesný název archivu je ve výpisu `funpkg -q .`. `-i` ponechává předchozí záznamy verzí v package DB. Izolovaný test na cílovém NASu také ověřil, že upravený `config.json` zůstává zachován při instalaci, upgrade i návratu na starší verzi.

### Bezpečnostní hranice

Browser updater neprovádí automatickou zálohu, restart ani rollback. Před kliknutím je nutné zálohovat soubory uvedené v `/ffp/funpkg/installed/ffp-webui-*`, celý `/ffp/etc/ffp-webui/` a související záznamy balíčků; po instalaci je nutný ruční restart služby. Dokud služba neběží z nových souborů, backend může být starý a statické soubory nové. Aktualizace proto není atomická ani transakční. WebUI zobrazuje tuto hranici před potvrzením; plnohodnotný oddělený supervisor s automatickým recovery/rollbackem není součástí v0.10.0.

Na cílovém NSA320 bylo ověřeno `funpkg -i` instalačního archivu v0.10.0, restart a health endpoint. Záloha payloadu, konfigurace a původních package records byla ověřena součty; její obnova vrátila službu na 0.9.4. Firmware zdrojové soubory mapují balíčkové příkazy na `zy-pkgs` a posílají je přes same-origin broker do privilegovaného `zysh-cgi`. FFP-WebUI tento endpoint neproxyuje, protože přenos relace/ověření a úplný kontrakt odpovědí z odděleného originu nebyl ověřen; Zypkg akce proto zůstávají v nativních firmware stránkách. Veřejný GitHub digest potvrzuje byte-for-byte shodu s API odpovědí, není však podpisem vydavatele a nechrání před kompromitací účtu repozitáře.
