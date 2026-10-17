# Where the absorbed amounts come from

Sources behind the "Absorbed amounts" tables in `RECIPE_RULES.md`. The same
frying rates are used by Convert recipe (`FRY_TYPE_RATES` in
`recipe_matcher.py`, `lib/utils/fry_types.dart` in the app).

The table came over from the old generation prompt on 28 Sep 2026 with no
sources. Only the karaage/tempura split (16 Oct) was researched at the
time. Every row was checked against published data on 17 Oct; this file
records what was found.

**Units:** every rate is grams of oil (or marinade) kept per 100 g of the raw
food. The Japanese sources call this 吸油率 and count the coating as part of
the food. The European tables give grams per 100 g of the dish's
ingredients.

## Main sources

| Short name | Source | What it gives |
|---|---|---|
| **Bognár** | Bognár A. (2002). *Tables on weight yield of food and retention factors of food constituents for the calculation of nutrient composition of cooked foods (dishes)*. BFE-R-02-03, Federal Research Centre for Nutrition, Karlsruhe. [FAO copy](https://www.fao.org/uploads/media/bognar_bfe-r-02-03.pdf) | Fat uptake in g per 100 g of ingredients, by food group and cooking method (Tables 2–38) |
| **Basic Data** | 女子栄養大学出版部『調理のためのベーシックデータ 第5版』, as quoted by [おいしい健康](https://oishi-kenko.com/articles/condition_fried_food) and [Wikipedia 吸油率](https://ja.wikipedia.org/wiki/%E5%90%B8%E6%B2%B9%E7%8E%87) | Japanese dietitians' standard reference: rates by frying style, chicken and potato cuts |
| **Kyotango** | Kyotango City health office, [揚げ物の種類によって違う吸油量](https://www.city.kyotango.lg.jp/material/files/group/25/oil.pdf) | Ranges per 80 g of food, by frying style |
| **TMD** | Tokyo Medical and Dental University Hospital, clinical nutrition dept., [recipe sheet 031](https://www.tmd.ac.jp/medhospital/column/recipe/pdf/031.pdf) | Ranges by frying style and for high-water vegetables |
| **Kumitasu** | [くみたす](https://www.kumitasu.com/contents/hyoji/3565), citing 日本栄養改善学会『食事調査マニュアル』改訂2版 (2008) and the 日本食品標準成分表2015 | Reference rates per 100 g of food plus coating |
| **USDA** | FoodData Central, SR Legacy: [170026](https://fdc.nal.usda.gov/food-details/170026/nutrients) raw potato (water 79.25 g, fat 0.09 g), [169677](https://fdc.nal.usda.gov/food-details/169677/nutrients) potato chips (water 1.86 g, fat 34.0 g), [167812](https://fdc.nal.usda.gov/food-details/167812/nutrients) raw pork belly (fat 53 g) | Compositions for the mass-balance checks below |

## Frying oil, row by row

| Row | Current | What the sources say | Verdict |
|---|---|---|---|
| Breaded (panko, breadcrumbs) | 12% (was 20%) | Kyotango フライ 10–20%; TMD 15–20%; Basic Data fish fry 10%; Kumitasu 10% (15% thick coating); Bognár breaded meat, poultry, fish and seafood, deep-fried: 4–6 g (Tables 5, 7, 13, 17, 21, 23, 25) | **20% is the top of the range.** Japanese sources centre on 10–15%, and the European tables are lower. A median-based figure would be about **12%**. |
| Wet-battered (tempura, kwek-kwek) | 15% | Basic Data tempura 15%; TMD 15–20%; Kyotango 15–25%; Kumitasu 10% (15% thick batter) | **Supported.** |
| Dry starch-dusted (karaage) | 8% | Basic Data karaage (potato starch) 8%; Kyotango 6–8% (flour absorbs more than starch); TMD 5–7%; Kumitasu 10%; Bognár breaded chicken, deep-fried, 4 g | **Supported** (researched 16 Oct). |
| Wrapper-enclosed (spring rolls, gyoza) | 12% | [FYTTE](https://fytte.jp/news/diet/191507/) (dietitian-reviewed) 春巻き 12%, no source given; [オリーブオイルをひとまわし](https://www.olive-hitomawashi.com/column/2019/04/post-4570.html) uses 10%, based on the 2020 food composition tables | **Weakly supported.** Two secondary sources give 10–12%; no primary data found. |
| Unbreaded lean meat, fish, tofu, vegetables | 5% meat, fish, tofu; 10% vegetables (was 7% for all) | Basic Data plain-fried chicken 5%; Kyotango 素揚げ 3–8%; Wikipedia 2–15%; Bognár unbreaded meat and poultry 0 g, low-fat fish 1 g, crustaceans 1 g; TMD high-water vegetables: eggplant ~14%, shishito ~10%, mushrooms ~20% | **One rate doesn't fit both.** Lean meat and fish keep little (0–5%); watery vegetables keep a lot (10–20%). A split would be more accurate: **meat, fish, tofu ≈ 5%; vegetables ≈ 10%**. |
| Thick starchy pieces (fries, plantain) | 5% | Bognár French fries, deep-fried: 5 g (Table 31); Basic Data potato wedges 2%, sticks (1 cm) 4% | **Supported.** |
| Thin starchy slices (chips) | 13% (was 30%) | Basic Data potato slices (1.5 mm) 15%. USDA mass balance: 100 g raw potato has 20.7 g of solids; chips are 64.1% non-fat solids, so it makes about 32 g of chips holding about 11 g of oil (34%). That's **≈11% of the raw weight** | **30% is about 2–3× too high.** Both sources give 11–15%, so **≈12–15%**. (30% looks like the oil content *of the chip*, about 34%, mistaken for the share of the raw potato.) |
| Pan-fried fish, unbreaded | 8% | Kalogeropoulos, Andrikopoulos & Hassapidou (2004), *Dietary evaluation of Mediterranean fish and molluscs pan-fried in virgin olive oil* ([AGRIS](https://agris.fao.org/search/en/records/65de312e0f3e94b9e5cba7c4)): 4.5–14.2% of fresh weight, lower for fattier and larger fish; Bognár low-fat fish, fried: 1 g | **Supported** as a middle figure; small lean fish keep more. |
| Fatty cuts, unbreaded (pork belly, skin-on) | 0% | Bognár pork and chicken, unbreaded, fried: fat uptake 0, fat retention 0.75 (Tables 6, 12); grilled pork belly loses 21–28% of its fat ([Nutrition Research and Practice 2025](https://e-nrp.org/pdf/10.4162/nrp.2025.19.6.1002)); Basic Data notes that meat and fish can lose fat into the oil | **Supported.** |

Sautés, stir-fries, stews and braises count all the oil, because it stays in the dish. That is a definition, not a measured rate.

## Marinades

| Row | Current | What the sources say | Verdict |
|---|---|---|---|
| Drained marinade, meat grilled or fried | 5% of raw meat weight | Tkacz et al. (2021), *Meat Science*: beef, 24 h at 4 °C, 3.3–4.4% uptake ([record](https://cris.unibo.it/handle/11585/829503)); Fencioglu et al. (2022), *Foods*: beef steak, 2 h vinegar marinades, 3.12–4.13% ([PMC9602021](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9602021/)); Rahman et al. (2023), *Food Quality and Safety* review: tumbled chicken ~6% ([fyad027](https://academic.oup.com/fqs/article/doi/10.1093/fqsafe/fyad027/7191307)) | **Supported**: 3–6% measured. |
| Same, thin slices (bulgogi, tapa, yakiniku) | 8% | No direct measurement found. Thin slices have more surface per gram, so they should be above whole cuts. | **Estimate.** Keep it, but say so. |
| Marinade cooked down or used as sauce | All of it | Definition: nothing is discarded. | — |

TMD's karaage recipe counts about 50% of the soy-sauce marinade as absorbed. That's a share of the marinade, not of the meat, and fits a small marinade that isn't drained.

## Brines and pickles

`vegetable water ÷ (vegetable water + brine liquid)` assumes the salt, sugar and vinegar even out between the vegetable's water and the brine. It's a diffusion model, not a measured rate; no published figure was found to check it against. **Estimate.**

## Changes made (17 Oct 2026)

Arianna approved the three suggested changes. `RECIPE_RULES.md`, the
worker's `FRY_TYPE_RATES` and the app's `fry_types.dart` now use:

1. **Breaded:** 20% → 12%.
2. **Thin-sliced (chips):** 30% → 13%, between the USDA mass balance (11%)
   and Basic Data (15%).
3. **Unbreaded:** split into `unbreaded` (lean meat, fish, tofu, 5%) and
   `unbreaded veg` (10%). Convert recipe uses `unbreaded veg` when a recipe
   has no meat, fish, tofu or starchy food to fry, only vegetables.

All other rows match the sources.
