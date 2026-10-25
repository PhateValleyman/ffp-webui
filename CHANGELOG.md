# Changelog

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
