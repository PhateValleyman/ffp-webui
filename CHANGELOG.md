# Changelog

## 0.9.1 — 2026-10-25

- Rozděleno ukládání Luanti cest od úplného nastavení: cesty lze uložit před výběrem hry, světa nebo servisního účtu.
- Výchozí cesty odpovídají rozložení z NAS: `/ffp/bin/luantiserver`, `/ffp/etc/luanti/minetest.conf`, `/ffp/home/root/.minetest/games`, `worlds`, `mods`, `skins` a `data`.
- Předchozí automaticky zvolené výchozí cesty se migrují na nové hodnoty; vlastní cesty se zachovávají.
- Podporují se symlinkované nadřazené FFP home adresáře, přičemž překryvy s interním stavem WebUI se kontrolují po vyhodnocení skutečné cesty.
- Ověření: Python unit testy, Go testy, syntaxe frontendu/backendu, HTTP smoke test a kontrola SHA-256. Cílový NAS nebyl aktualizován.
