# Where the absorbed amounts come from

Sources behind the "Absorbed amounts" tables in `RECIPE_RULES.md`. This
file is the research record: why each rate is what it is. The frying rates
themselves have one working copy, the app project's `fry_types` table
(blobbapp migration `20261028120000_create_fry_types.sql`, 28 Oct 2026),
which the worker, the app's editor, blobb.app/sources and RECIPE_RULES.md's
table all read.

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
| **Nawata** | 縄田敬子, 竹下尚男, 石田裕美 (2005). 食事調査標準化のためのフライ調理の吸油率に関する基礎的検討 (Nawata K., Takeshita M., Ishida H., *Absorption rate of frying oil by breaded deep-fried foods for standardization in a dietary survey*). 栄養学雑誌 (Jpn. J. Nutr. Diet.) 63(6): 339–345. [J-STAGE PDF](https://www.jstage.jst.go.jp/article/eiyogakuzashi1941/63/6/63_6_339/_pdf) | Coating that stuck, as % of the raw food's weight: flour, egg and dry breadcrumbs on five foods, each coated by 5–6 home cooks their usual way (Table 1) |
| **MEXT** | 文部科学省 科学技術・学術審議会 資源調査分科会, 日本食品標準成分表2015年版（七訂）, 揚げ物における衣の割合及び脂質量の増減, 表17. [PDF](https://www.mext.go.jp/component/a_menu/science/detail/__icsFiles/afieldfile/2016/11/08/1365334_1-0320r3.pdf) | Weights of raw food and of each coating component (flour or mix, breadcrumbs, egg) per 100 g of 14 fried foods, and the fat each gained |
| **USDA** | FoodData Central, SR Legacy: [170026](https://fdc.nal.usda.gov/food-details/170026/nutrients) raw potato (water 79.25 g, fat 0.09 g), [169677](https://fdc.nal.usda.gov/food-details/169677/nutrients) potato chips (water 1.86 g, fat 34.0 g), [167812](https://fdc.nal.usda.gov/food-details/167812/nutrients) raw pork belly (fat 53 g) | Compositions for the mass-balance checks below |

## Frying oil, row by row

| Row | Current | What the sources say | Verdict |
|---|---|---|---|
| Breaded (panko, breadcrumbs) | 12% (was 20%) | Kyotango フライ 10–20%; TMD 15–20%; Basic Data fish fry 10%; Kumitasu 10% (15% thick coating); Bognár breaded meat, poultry, fish and seafood, deep-fried: 4–6 g (Tables 5, 7, 13, 17, 21, 23, 25) | **20% is the top of the range.** Japanese sources centre on 10–15%, and the European tables are lower. A median-based figure would be about **12%**. |
| Wet-battered (tempura, kwek-kwek) | 15% | Basic Data tempura 15%; TMD 15–20%; Kyotango 15–25%; Kumitasu 10% (15% thick batter) | **Supported.** |
| Dry starch-dusted tofu, fish, seafood | 8% | Basic Data karaage (potato starch) 8%; Kyotango 6–8% (flour absorbs more than starch); TMD 5–7%; Kumitasu 10%; MEXT 2020 small whole horse mackerel, flour-dusted, +9.7 g | **Supported** (researched 16 Oct; meat split off 25 Nov). |
| Dusted meat and poultry, skinless | 4.3% | MEXT 2020 Table 13 skinless chicken thigh karaage +4.3 g per 100 g raw; Bognár breaded chicken, deep-fried, 4 g | **Measured** (25 Nov 2026), below. |
| Wrapper-enclosed (spring rolls, lumpia, gyoza) | 8% (was 12%) | **USDA FNDDS** fried egg rolls ([2708702](https://fdc.nal.usda.gov/food-details/2708702/nutrients) with pork, 2708701 with shrimp, 2708700 meatless) are each 100 g of prepared frozen egg roll + 8 g vegetable oil; SR Legacy's lab-analysed restaurant egg rolls ([167667](https://fdc.nal.usda.gov/food-details/167667/nutrients)) have 11.9 g fat per 100 g in all, filling included. [FYTTE](https://fytte.jp/news/diet/191507/) (dietitian-reviewed) 春巻き 12%, no source given; [オリーブオイルをひとまわし](https://www.olive-hitomawashi.com/column/2019/04/post-4570.html) uses 10%. No study measures spring rolls themselves | **USDA's figure, 8%** (3 Nov 2026). The two dietitian figures have no data behind them. |
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

## Coatings

Flour, egg wash and crumbs set out for coating are mostly left in the bowl.
The rate is the coating that stays on the food, as % of the raw food's
edible weight (the same basis as the oil rates). Both sources weighed the
coating material before and after coating; Nawata's cooks coated the food
the way they do at home.

MEXT Table 17 gives grams per 100 g of fried food; the figures below divide
each coating weight by that row's raw-food weight.

| Row | Rate | Nawata (Table 1) | MEXT (Table 17) | Verdict |
|---|---|---|---|---|
| Flour before egg (breaded) | 3.5% | Pork loin 2.7, pork fillet 3.6, salmon 3.0, horse mackerel 3.8, shrimp 3.7; **mean 3.4 ± 0.5** | Fish fry: horse mackerel 4.3, sardine 5.2, mackerel 3.6, pollock 3.2 | **Supported**: the two agree. |
| Egg wash | 9% | Pork loin 7.9, pork fillet 9.5, salmon 6.3, horse mackerel 8.9, shrimp 7.1; **mean 7.9 ± 1.3** | Fish fry: 10.1, 12.6, 7.0, 7.8 (mean 9.4) | **Between the two means.** |
| Dry breadcrumbs or panko | 9.5% | Pork loin 8.2, pork fillet 9.9, salmon 6.9, horse mackerel 9.7, shrimp 6.8; **mean 8.3 ± 1.5** (crumbs soaked in water: 13.1, one cook) | Fish fry: 9.9, 13.4, 7.0, 7.2; tonkatsu loin 9.3, fillet 10.9 (mean of six 9.6) | **Between the two means.** |
| Flour or starch on a dry surface | 3.5% | — | Small horse mackerel karaage, flour: 3.5 | **One measurement**, the same as flour before egg. |
| Flour or starch on a wet surface (marinated, buttermilk-soaked) | 15% | — | Chicken thigh karaage, karaage mix (から揚げ粉): skin-on 14.3, skinless 15.6 | **The only wet-surface measurement found.** Taken with a seasoned karaage mix, not plain flour. |

A wet surface holds four times the flour of a dry one. Meat and fish
differed little next to the spread between cooks (Nawata), so the rates
aren't split by food.

**MEXT 2020 (eighth edition), Table 13** (揚げ物等における衣の割合及び脂質量の増減, checked 25 Nov 2026) repeats the 2015 karaage rows: chicken thigh with karaage mix (から揚げ粉), coating 14.3 g (skin-on) and 15.6 g (skinless) per 100 g raw; small horse mackerel with flour 3.5 g. It still has no row for plain potato starch or flour on marinated meat. Its fat column is the one that matters for fried chicken: skin-on thigh karaage **−0.7 g** per 100 g raw (no net oil), skinless **+4.3 g**, horse mackerel +9.7 g. So coated skin-on chicken takes no frying oil in the recipes (RECIPE_RULES.md). [PDF](https://www.mext.go.jp/content/20201225-mxt_kagsei-mext_01110_011.pdf), pp. 58–59.

**Cap.** Recipes set out less than 15% for plain-starch karaage: RecipeTin Japan 20 g cornstarch for 350 g (5.7%), Just One Cookbook 2 tbsp flour + 2 tbsp starch for 1½ lb (about 5%), Tasting Table 3 tbsp + 3 tbsp for 1 lb (about 11%). A coating that the cook didn't set out can't stick, so the rate is capped at the most a recipe's sources set out per gram of food. Southern fried chicken's sources set out 30–40% (RecipeTin Eats 2¼ cups flour and ¾ cup cornstarch for 1.8 kg; Jo Cooks 2 cups for 2 lb), so 15% stands there.

Not found: a measurement of plain flour on buttermilk-soaked chicken, or of
home dredging in English. Food-science papers on industrial batters and
breadings report 11–36% pickup ([Effect of breading particle size on coating
adhesion in breaded, fried chicken breasts](https://www.researchgate.net/publication/230173131_Effect_of_breading_particle_size_on_coating_adhesion_in_breaded_fried_chicken_breasts)),
which is a factory process, not a home dredge.

**Wet batter (tempura, kwek-kwek): 11% of the raw food, flour and starch
only** (16 Nov 2026). MEXT Table 17's tempura rows give the dry tempura mix
that stayed on each food, divided by its raw weight: sweet potato 6.1,
eggplant 11.1, Japanese whiting (kisu) 13.3, whiteleg shrimp 12.7, squid
10.8; mean 10.8. Their batter was tempura mix and water at 39:61, a thin
batter, so a thick one (kwek-kwek's) likely carries a little more; no
measurement of one was found. The batter's egg, water and seasoning scale
with its flour, by the recipe's own ratio. Listing the whole bowl had
counted 7.8 g of flour on each 9 g quail egg.

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

## One copy of the rates (28 Oct 2026)

The worker's `FRY_TYPE_RATES`, the app's `fry_types.dart` rates, the
Sources page's rows and RECIPE_RULES.md's table were four copies kept in
step by hand. They now all come from the `fry_types` table, which also has
the three rows Convert recipe never had: wrapped (12% then, 8% since 3 Nov), pan-fried fish (8%)
and fatty cut (0%). The rates are a share of the fried food's **edible**
weight, as its calories are: the 27 Oct "bone and all" division in the
matcher had no source behind it and was dropped.

## Wrapped: 12% to 8% (3 Nov 2026)

A converted lumpia (1 lb pork for 12 rolls) came out at 204 kcal a roll,
a third of it oil, with about twice the fat per gram of USDA's egg rolls.
USDA FNDDS builds its fried egg rolls with 8 g of oil per 100 g of roll,
the only figure found with data behind it; Arianna approved 8%. The rolls'
remaining extra fat is their filling: lumpia shanghai is mostly ground
pork (21% fat raw), egg rolls mostly cabbage.

## Dusted meat: 4.3% (25 Nov 2026)

The dusted rate (8%) came from the Japanese dietitians' tables, which weigh
the oil gone from the pot: that also counts oil left on the pot, strainer and
paper, and doesn't subtract fat the food gives up. MEXT 2020 Table 13
analyses the fat in the raw food and coating and again after frying, so its
figure is net. Its two dusted fries differ by food, not coating: skinless
chicken thigh with karaage mix +4.3 g per 100 g raw, a small whole horse
mackerel with flour +9.7 g. Its tempura rows show the same pattern: chicken
tenderloin +6.0, shrimp +9.9, squid +12.2, eggplant +15.2, mushrooms
+20.8 to +32.3. Wet, lean, high-surface foods take the most oil.

So meat and poultry dusted or dredged without skin have their own fry type,
`dusted meat`, at MEXT's 4.3%, and tofu, fish and seafood stay at 8% (agedashi
tofu matches Cup of Yum's 163 at 8%; at 4.3% it would be about 131). USDA
FNDDS's coated fried chicken thigh (2706045, skin-on) is built with 7 g of oil
per 78 g of cooked thigh, about 6–7% of the raw weight: a recipe assumption,
not a measurement. Arianna, 25 Nov 2026; blobbapp migration
`20261125130000_dusted_meat_fry_type.sql`.
