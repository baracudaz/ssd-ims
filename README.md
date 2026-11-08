# Integrácia Stredoslovenskej distribučnej (SSD IMS) pre Home Assistant

*English: a Home Assistant integration for the SSD energy data portal (ims.ssd.sk). User documentation is in Slovak; developer documentation is in English in [DEVELOPMENT.md](DEVELOPMENT.md).*

Integrácia sťahuje údaje o spotrebe a dodávke elektriny z Portálu energetických dát <https://ims.ssd.sk> a automaticky ich ukladá do dlhodobých štatistík Home Assistantu, odkiaľ ich zobrazí panel Energie.

![Panel Energie](artifacts/screenshots/energy-usage.png)

## Funkcie

- **Import štatistík**: historické aj denné údaje sa automaticky ukladajú do databázy štatistík Home Assistantu
- **Pripravené pre panel Energie**: údaje sa dajú priamo použiť v paneli Energie
- **Registre VT/NT**: mesačné stavy registrov vysokej a nízkej tarify a maximálny výkon z elektromera, voliteľne aj náklady podľa vašich cien
- **Viac odberných miest**: sledovanie viacerých odberných miest naraz
- **Vlastné názvy odberných miest**: napr. adresa alebo názov bytu
- **Import histórie**: pri nastavení sa dajú načítať údaje až 365 dní dozadu
- **Automatické aktualizácie**: nastaviteľný interval (6, 12 alebo 24 hodín)
- **Opätovné prihlásenie**: keď prihlasovacie údaje prestanú platiť, Home Assistant vás vyzve na ich zadanie bez odstránenia integrácie
- **Rekonfigurácia**: výber a názvy odberných miest zmeníte kedykoľvek cez **Rekonfigurácia**
- **Diagnostika**: diagnostické údaje na riešenie problémov (bez prihlasovacích údajov a čísel odberných miest)

## Aké údaje sú k dispozícii

**Aktuálnosť**: portál zverejňuje údaje raz denne po polnoci:

- údaje za aktuálny deň nie sú k dispozícii,
- najnovšie údaje sú za včerajšok.

**Rozlíšenie**: portál meria v 15-minútových intervaloch, integrácia ich sčíta na hodinové štatistiky.

**Registre**: registre elektromera (1.8.1 = VT, vysoká tarifa; 1.8.2 = NT, nízka tarifa; 1.6.0 = maximálny štvrťhodinový výkon) pochádzajú zo stránky portálu *Registrové údaje*. Sú to priebežné stavy počítadiel, odčítané **raz mesačne** (o 00:00 prvého dňa v mesiaci, občas aj mimo poradia). Rozdelenie spotreby na VT a NT je preto známe len po mesiacoch. 15-minútový profil rozdelenie na tarify neobsahuje a portál nezverejňuje ani časy prepínania HDO.

## Entity

Pre každé odberné miesto vznikne **8 entít**:

| Entita | Popis |
|--------|-------|
| `sensor.<pod_name>_actual_consumption_yesterday` | Spotreba za včerajšok (kWh) |
| `sensor.<pod_name>_actual_supply_yesterday` | Dodávka do siete za včerajšok (kWh) |
| `sensor.<pod_name>_actual_consumption_total` | Celková spotreba zo štatistík (kWh) |
| `sensor.<pod_name>_actual_supply_total` | Celková dodávka zo štatistík (kWh) |
| `sensor.<pod_name>_last_update` | Čas poslednej aktualizácie |
| `sensor.<pod_name>_high_tariff_meter_reading` | Posledný mesačný stav registra VT, 1.8.1 (kWh) |
| `sensor.<pod_name>_low_tariff_meter_reading` | Posledný mesačný stav registra NT, 1.8.2 (kWh) |
| `sensor.<pod_name>_peak_demand` | Maximálny štvrťhodinový výkon za posledné obdobie, 1.6.0 (kW) |

Entity registrov majú atribúty `reading_time` (čas odpočtu) a `meter_serial_number` (výrobné číslo elektromera).

## Dlhodobé štatistiky

Integrácia ukladá údaje do štatistík Home Assistantu po hodinách:

| ID štatistiky | Popis |
|---------------|-------|
| `ssd_ims:<pod_name>_actual_consumption` | Spotreba, kumulatívne (kWh) |
| `ssd_ims:<pod_name>_actual_supply` | Dodávka do siete, kumulatívne (kWh) |
| `ssd_ims:<pod_name>_consumption_vt` | Spotreba vo vysokej tarife, po mesiacoch (kWh) |
| `ssd_ims:<pod_name>_consumption_nt` | Spotreba v nízkej tarife, po mesiacoch (kWh) |
| `ssd_ims:<pod_name>_cost_vt` | Náklady vo vysokej tarife, po mesiacoch (EUR) — len ak je zadaná cena VT |
| `ssd_ims:<pod_name>_cost_nt` | Náklady v nízkej tarife, po mesiacoch (EUR) — len ak je zadaná cena NT |
| `ssd_ims:<pod_name>_actual_consumption_cost` | Hodinové náklady pre `actual_consumption` (EUR) — len ak je zadaná cena VT (bez ceny NT sa použije cena VT) |

Štatistiky VT/NT sú rozdiely medzi po sebe idúcimi odpočtami registrov. Hodnota za mesiac sa zapíše do poslednej hodiny mesiaca (odpočet o 00:00 1. decembra uzatvára november), takže mesačný a ročný pohľad v paneli Energie ukazujú správne rozdelenie a denný či hodinový pohľad ho ukáže ako jeden blok na konci mesiaca. Pri prvom nastavení sa načíta celá história registrov, ktorú portál má (až po montáž elektromera); prvý odpočet slúži len ako východisková hodnota. Cez výmenu elektromera sa rozdiel nepočíta.

`<pod_name>` vychádza z názvu, ktorý odbernému miestu dáte pri nastavení. **Ak odberné miesto neskôr premenujete (cez Rekonfigurácia), zmení sa ID jeho štatistík a začne sa nová séria** — doterajšia história sa neprenesie. Zvoľte názov, ktorý chcete ponechať, alebo po premenovaní upravte zdroj v nastaveniach panela Energie.

## Inštalácia

### Spôsob 1: Marketplace (odporúčané, Home Assistant 2026.11 a novší)

Od verzie 2026.11 je HACS súčasťou Home Assistantu ako **Marketplace**.

1. Otvorte **Nastavenia** → **Marketplace** (pri prvom otvorení potvrďte upozornenie)
2. Vyhľadajte „Stredoslovenská distribučná (SSD IMS)“ a otvorte ju
3. Zvoľte **Inštalovať**, skontrolujte verziu a znova zvoľte **Inštalovať**
4. Hneď sa otvorí nastavenie integrácie; ak Home Assistant potrebuje najprv reštart, ponúkne ho v časti **Opravy**

Ak ste integráciu nainštalovali cez HACS pred verziou 2026.11, nemusíte nič robiť: pri prvom spustení po aktualizácii Marketplace prevezme správu od HACS a integrácia zostane nainštalovaná a bude dostávať aktualizácie (v časti **Nastavenia** → **Aktualizácie**).

### Spôsob 2: HACS (Home Assistant starší ako 2026.11)

1. Otvorte HACS
2. Zvoľte „Integrations“
3. Kliknite na tlačidlo „+“
4. Vyhľadajte „Stredoslovenská distribučná (SSD IMS)“
5. Zvoľte „Install“
6. Reštartujte Home Assistant

### Spôsob 3: Ručná inštalácia

1. Stiahnite tento repozitár
2. Skopírujte priečinok `custom_components/ssd_ims` do priečinka `config/custom_components/` vo vašom Home Assistante
3. Reštartujte Home Assistant
4. Pridajte integráciu (pozri [Nastavenie](#nastavenie))

### Prechod na verziu 2.3.0

Aktualizácia si nevyžaduje žiadny zásah: všetky doterajšie štatistiky, entity a nastavenia zostanú. Po reštarte integrácia sama pridá entity registrov a načíta štatistiky `consumption_vt` / `consumption_nt` s celou históriou registrov.

Ak chcete v paneli Energie vidieť aj náklady:

1. V možnostiach integrácie zadajte ceny (pozri [Ceny a náklady](#ceny-a-náklady)) — pri jednotarifnej sadzbe (D1, D2) stačí cena VT.
2. V nastaveniach panela Energie upravte pripojenie k sieti so štatistikou `ssd_ims:<pod_name>_actual_consumption` a v časti **Sledovanie nákladov** zvoľte **Použiť entitu sledujúcu celkové náklady** → `ssd_ims:<pod_name>_actual_consumption_cost`. Náklady za celú importovanú spotrebu sa vypočítajú do minúty po uložení cien.

Majte na pamäti:

- **Nepridávajte do panela Energie aj štatistiky VT/NT** — merajú tú istú energiu ako `actual_consumption`, takže by sa započítala dvakrát.
- **Celá história sa ocení aktuálnou cenou.** V minulých rokoch boli ceny iné, takže staršie náklady sú len orientačné.

## Nastavenie

1. Otvorte **Nastavenia** → **Zariadenia a služby**
2. Zvoľte **Pridať integráciu**
3. Vyhľadajte „Stredoslovenská distribučná (SSD IMS)“
4. **Krok 1 – prihlásenie**: zadajte prihlasovacie údaje do portálu <https://ims.ssd.sk>
5. **Krok 2 – odberné miesta**: vyberte odberné miesta, ktoré chcete sledovať
6. **Krok 3 – názvy**: zadajte vlastné názvy odberných miest (nepovinné, napr. adresa)
7. **Krok 4 – import a aktualizácie**: nastavte interval aktualizácie a import histórie

| Nastavenie | Predvolené | Popis |
|------------|------------|-------|
| Interval aktualizácie | 6 hodín | Ako často sa majú kontrolovať nové údaje (6, 12 alebo 24 hodín) |
| Import histórie | Áno | Pri prvom nastavení načítať aj staršie údaje |
| Počet dní | 7 | Koľko dní dozadu načítať (1 – 365) |

### Možnosti

Po nastavení môžete tieto položky zmeniť v **Nastavenia** → **Zariadenia a služby** → **Stredoslovenská distribučná (SSD IMS)** → **Konfigurovať**:

| Možnosť | Popis |
|---------|-------|
| Interval aktualizácie | Ako často sa majú kontrolovať nové údaje |
| Cena vo vysokej tarife (VT) | Nepovinné. Koncová cena za 1 kWh v EUR vrátane DPH a všetkých poplatkov — zapne hodinové náklady `actual_consumption_cost` a mesačné `cost_vt` |
| Cena v nízkej tarife (NT) | Nepovinné. To isté pre NT — zapne mesačné `cost_nt`. Pri jednotarifnej sadzbe (D1, D2) nechajte prázdne, celá spotreba sa vypočíta s cenou VT |

## Ceny a náklady

**Kde nájdete ceny:** na faktúre od dodávateľa (napr. SSE ich uvádza pod nadpisom *Aktuálne koncové ceny elektriny platné pre Vašu sadzbu*). Použite tieto koncové ceny a nesčítavajte položky faktúry sami — koncová cena už obsahuje silovú elektrinu, distribúciu, straty, regulované poplatky za kWh (tarifa za prevádzkovanie systému TPS, tarifa za systémové služby TSS, odvod do Národného jadrového fondu NJF) aj DPH, ktoré sa pri ručnom sčítaní ľahko vynechajú. Mesačné poplatky (platba dodávateľovi, distribúcia podľa ističa) sa v paneli Energie zobraziť nedajú a nie sú zahrnuté.

**Prečo ceny v integrácii:** Home Assistant uplatní cenu nastavenú v paneli Energie len na štatistiky entít, nie na importované (externé) štatistiky, aké vytvára táto integrácia. Integrácia preto počíta vlastné štatistiky nákladov, ktoré zvolíte cez **Použiť entitu sledujúcu celkové náklady**. Ceny aj náklady sú vždy v eurách a panel Energie ich označí menou Home Assistantu, preto si v nastaveniach domácnosti (**Mena**) nastavte EUR.

**Zmena cien:** uložením možností sa ceny uplatnia hneď. Prvý import ocení celú históriu aktuálnou cenou. Po zmene ceny si mesačné `cost_vt` / `cost_nt` ponechajú pôvodnú cenu pre už importované mesiace, kým hodinové `actual_consumption_cost` sa prepočítajú novou cenou za posledné tri obdobia registrov (zhruba posledné dva mesiace a aktuálny mesiac); staršie hodiny si ponechajú pôvodnú cenu.

## Panel Energie

1. Otvorte nastavenia panela Energie (**Nastavenia** → **Panely** → **Energie**, prípadne adresa `/config/energy`)
2. V časti **Elektrická sieť** zvoľte **Pridať sieťové pripojenie**
3. V poli **Energia dovážaná zo siete** vyhľadajte `ssd_ims:<pod_name>_actual_consumption` (podľa názvu, ktorý ste odbernému miestu dali pri nastavení)
4. Ak dodávate elektrinu do siete (napr. z fotovoltiky), v poli **Energia vyvážaná do siete** zvoľte `ssd_ims:<pod_name>_actual_supply`
5. Ak chcete náklady, v časti **Sledovanie nákladov** zvoľte **Použiť entitu sledujúcu celkové náklady** a štatistiku nákladov (pozri nižšie)

**Odporúčané — hodinová spotreba s nákladmi:** `ssd_ims:<pod_name>_actual_consumption` s nákladmi `ssd_ims:<pod_name>_actual_consumption_cost`. Fungujú denné, týždenné, mesačné aj ročné pohľady. Náklady každej hodiny sú jej kWh × priemerná cena obdobia registrov, vážená pomerom VT/NT v tomto období — mesačné náklady sú teda presné, rozdelenie na hodiny je priemer (portál nezverejňuje, kedy HDO prepínalo tarify). Hodiny po poslednom odpočte (aktuálny mesiac) sa ocenia pomerom predchádzajúceho obdobia a po zverejnení odpočtu sa automaticky opravia. Náklady existujú len pre hodiny, ktorých spotreba bola importovaná (pozri *Počet dní*).

**Alternatíva — mesačné rozdelenie VT/NT:** `ssd_ims:<pod_name>_consumption_vt` s nákladmi `ssd_ims:<pod_name>_cost_vt` a `ssd_ims:<pod_name>_consumption_nt` s nákladmi `ssd_ims:<pod_name>_cost_nt`. Ukazuje skutočné rozdelenie VT/NT po mesiacoch, ale denné a týždenné pohľady zostanú prázdne, lebo registre sa odčítavajú len raz mesačne.

**Použite len jednu z možností, nie obe** — merajú tú istú energiu, takže by sa započítala dvakrát. Štatistiky VT/NT si môžete zobraziť mimo panela Energie, napr. v karte **Štatistický graf** s mesačným obdobím.

## Riešenie problémov

1. **Prihlásenie zlyhalo**
   - Overte meno a heslo na <https://ims.ssd.sk>
   - Skontrolujte, či je váš účet aktívny
   - Ak sa prihlasovacie údaje zmenili, Home Assistant vás upozorní a ponúkne opätovné prihlásenie bez odstránenia integrácie

2. **Panel Energie neukazuje údaje**
   - Počkajte na prvú aktualizáciu (podľa intervalu to môže trvať až 6 hodín)
   - V protokoloch skontrolujte, či sa import histórie dokončil
   - Overte, či sú v paneli Energie zvolené správne štatistiky

3. **Chyba certifikátu SSL**
   - Portál SSD IMS používa SSL; Home Assistant musí vedieť overiť certifikáty
   - Skontrolujte, či sú certifikáty certifikačných autorít vo vašom systéme aktuálne

### Podrobné protokolovanie

Pri riešení problémov zapnite podrobné protokolovanie:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.ssd_ims: debug
```

Ak problém nahlasujete, pripojte diagnostické údaje (**Nastavenia** → **Zariadenia a služby** → integrácia → ⋮ → **Stiahnuť diagnostické údaje**) — neobsahujú prihlasovacie údaje ani čísla odberných miest.

## Autori

Spravuje [baracudaz](https://github.com/baracudaz). Pôvodne vychádza z projektu [HA-SSD-IMS](https://github.com/samsk/HA-SSD-IMS) od [samsk](https://github.com/samsk).

## Licencia

Projekt je licencovaný pod AGPLv3 — podrobnosti v súbore [LICENSE](LICENSE).

## Prispievanie

Vývoj, testy a postup pri prispievaní sú popísané (v angličtine) v [DEVELOPMENT.md](DEVELOPMENT.md).
