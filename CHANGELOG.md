# Changelog

## 0.11.0 — 2026-10-25

- Přidána samostatná správa Zypkg přes lokální `zysh -e`: čtecí dotazy ukazují původní výstup firmwaru; instalace, aktualizace, povolení/zakázání a odebrání používají pouze pevný seznam příkazů a vyžadují přesné potvrzení.
- FFP `funpkg` a `slacker` zůstávají oddělené. WebUI nevolá `zysh-cgi`, neprovádí automatické změny Zypkg a nepředstírá parsování neověřeného formátu katalogu.
- Během vývoje byly ověřeny pouze dostupné read-only příkazy na cílovém NSA320; žádná Zypkg instalace, aktualizace, změna stavu ani odebrání nebyly spuštěny. Mutující operace v rozhraní proto nebyly na NASu ověřeny.

## 0.10.0 — 2026-10-25

- Karta Balíčky odlišuje nativní Zypkg správu od FFP `funpkg`/`slacker` a nabízí přímé odkazy na dvě stránky firmware Zyxel. Volání neověřeného CGI protokolu není povoleno; instalaci Zypkg dál provádí firmware.
- FFP-WebUI automaticky kontroluje stabilní GitHub vydání a stáhne pouze ověřený FFP-WebUI `.txz` do stagingu; instalaci lze ručně spustit v prohlížeči. Na cílovém NASu byla v0.10.0 instalována přes `funpkg -i`, po restartu potvrzena přes health endpoint a následně vrácena z ověřené zálohy na původní v0.9.4; obě konfigurační položky zůstaly zachovány.
- Živý aktualizátor načetl GitHub Releases API; download-only test stáhl v0.9.5 do izolovaného dočasného stagingu, ověřil SHA-256 a neinstaloval ji. `funpkg -u` pro nový archiv přitom hlásí „Not installed“ i při existující starší verzi, proto updater používá `-i` a ověřuje přesný záznam v `funpkg -q .`. Zypkg aktualizace firmwaru zůstávají oddělené.

## 0.9.5 — 2026-10-25

- Luanti accepts `/ffp/home/root/.minetest` as `user_path` only when games, worlds, mods and skins are its immediate matching subdirectories; unrelated overlaps, nested paths and symlink aliases remain rejected.
- Added regression coverage for the supported root layout and rejected nested/symlinked layouts. The NAS was not changed or tested.

## 0.9.4 — 2026-10-25

- Luanti game IDs now follow engine rules: the folder name is used with a trailing `_game` removed (so `minetest_game` is `minetest`); legacy IDs from `game.conf` `aliases` resolve safely. A free-form `id` key is not treated as an ID.
- Game listing and world selectors expose canonical IDs. World creation and game changes save canonical IDs, and server start resolves legacy aliases and fails closed for missing or ambiguous games.
- Added regressions for the reported NAS folders/worlds, aliases, `_game` normalization and ambiguous matches. The NAS was not changed or tested.

## 0.9.3 — 2026-10-25

- Opraven výpis modů: jejich stav se čte z `load_mod_<název>` ve `world.mt` vybraného světa; bez záznamu je nový mod označen jako vypnutý a bez vybraného světa jako neznámý.
- Release obsahuje instalační `.txz`, README, zdrojový archiv a manifest SHA-256. NAS nebyl tímto vydáním měněn.

## 0.9.2 — 2026-10-25

- Luanti lze spustit pod vybraným existujícím systémovým účtem včetně `root`.
- Ukládání cest má samostatnou validaci a nevyžaduje výběr hry, světa ani servisního účtu; při neúspěšném zápisu zůstane aktivní i uložené nastavení beze změny.
- Běžné chyby souborového systému při ukládání se vracejí s konkrétním důvodem místo obecného hlášení.
- Zachovány výchozí cesty z 0.9.1. Ověření cílového NASu nebylo provedeno.

## 0.9.1 — 2026-10-25

- Rozděleno ukládání Luanti cest od úplného nastavení: cesty lze uložit před výběrem hry, světa nebo servisního účtu.
- Výchozí cesty odpovídají rozložení z NAS: `/ffp/bin/luantiserver`, `/ffp/etc/luanti/minetest.conf`, `/ffp/home/root/.minetest/games`, `worlds`, `mods`, `skins` a `data`.
- Předchozí automaticky zvolené výchozí cesty se migrují na nové hodnoty; vlastní cesty se zachovávají.
- Podporují se symlinkované nadřazené FFP home adresáře, přičemž překryvy s interním stavem WebUI se kontrolují po vyhodnocení skutečné cesty.
- Ověření: Python unit testy, Go testy, syntaxe frontendu/backendu, HTTP smoke test a kontrola SHA-256. Cílový NAS nebyl aktualizován.
