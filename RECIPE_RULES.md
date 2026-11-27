# Recipe template rules

Read this before generating recipe templates or running `parse_recipe.py`.
It is the prompt given to the AI that writes `{cuisine}_recipes.txt`, and the
rules those files must follow. Templates are user-facing: people open them to
check what a meal contains, so every amount must be one they recognise.

The only rules file (11 Oct 2026). The earlier copies (the v2 root
`RECIPE_RULES.md`, `recipe_generation_prompt.md`) are retired in
`Blobb App/_to_delete_from_templates/`.

---

I'm building recipe templates for a food tracking app called Blobb. Generate a `.txt` file in the exact format below.
Output filename: `{cuisine}_recipes.txt`
Cuisine: (specify per run)
Include: mains, sides, soups, rice dishes, noodles, desserts, drinks, and any base components needed (sauces, batters, pastes, broths, glazes, marinades, prepared proteins, and compound ingredients that require their own cooking steps — e.g. chashu pork, braised pork belly, ajitsuke tamago)

## Research requirement

For EVERY recipe, research at least 3 real recipe sources before writing it. Cross-reference ingredient ratios across sources and synthesize a realistic composite. Each recipe ends with a `SOURCE:` line listing the actual URLs consulted. Sources must inform the ratios — never attach URLs after writing.

Source quality:
* Use real recipe pages (food blogs, publishers, brand/manufacturer recipe pages, culinary institutions). Prefer 3 different sites over 3 pages from one site.
* Prefer sites from the cuisine's own country and its brands' recipe pages (for Filipino: Panlasang Pinoy, Kawaling Pinoy, Foxy Folksy, Knorr PH, Del Monte PH, Mama Sita's).
* Do NOT use AI-generated wikis, aggregator/Q&A pages, scraped mirror sites, or forum posts.
* Open every URL before citing it: it must load as that recipe's page. Never guess or rebuild a URL's path (21 Oct 2026: two guessed Just One Cookbook links were "Page not found").
* URLs must contain no commas or spaces. Percent-encode if needed (space → `%20`).
* Conversion and nutrition references (USDA densities, absorption figures) are cited in the chat response, not on the SOURCE line. SOURCE is for recipe pages only.

## Format

* `Category: X` at the top of the file
* 3 blank lines between every recipe block
* Each recipe block:

```
Recipe Name
ID: recipe_name
AKA: First alternate name", "Second name", "Third name
Servings: N
Serving size: 1 cup
ingredient lines
SOURCE: url1, url2, url3
```

`Serving size:` is required on base templates (see Base templates) and omitted on everything else.

### ID line

* The template's permanent id: share links and people's saved meals point at it. **Never change an existing recipe's `ID:`**, not even when renaming it; rename by editing the title line only.
* A new recipe's ID is its title in lowercase with every run of other characters as `_`, and a trailing `_` on a one-word title: `Miso Soup` → `ID: miso_soup`, `Salt-Grilled Mackerel` → `ID: salt_grilled_mackerel`, `Gyoza` → `ID: gyoza_`.
* Every ID is unique across all recipe files; the batch run stops on a repeat.
* The same title in two cuisines is fine: the app shows each with its cuisine tag. Only the ID changes: the existing recipe keeps its ID and the new one adds `_01` (then `_02`): `Fried Rice` in Chinese is `fried_rice`, in Filipino `fried_rice_01`.

### AKA line

* Zero alternate names → omit the `AKA:` line entirely
* Single AKA → no quotes (`AKA: Beef bowl`)
* Two or more → no opening quote on the first, no closing quote on the last, `", "` between each (`AKA: Beef bowl", "Gyudon`)
* Romanized local names only — NO kanji, kana, hangul, or other non-Latin script. Drop diacritics (`Ragu`, not `Ragù`).
* **The primary recipe name is the name people actually use** — what they'd type into search, read on a menu, or say out loud. When a dish is widely known by its romanized local name, that's the primary name (`Takoyaki`, `Katsudon`, `Gyoza`, `Tonkatsu`, `Karaage`, `Onigiri`); when people say the English name, that's the primary name (`Miso Soup`, `Teriyaki Chicken`, `Coffee Jelly`, `Matcha Latte`). The other name always goes in AKA, so either one finds the recipe. When unsure, ask what a menu or a supermarket label in Manila or the US would print. (Ingredient lines are different: they stay English, see below, because they have to match the food database.)

### Section headers

`--Section name` for sections within a recipe (`--Filling`, `--Sauce`, `--Absorbed oil`, `--Absorbed marinade`, `--Serving`).

### SOURCE line

Every recipe ends with `SOURCE:` and exactly 3 comma-separated URLs. The parser skips this line.

## Ingredient lines

Format: `qty unit ingredient` (`1 cup glutinous rice flour`, `3 tbsp soy sauce`, `2 whole egg`)

* **English names**, not local-language names (`green onion` not `negi`, `kelp` not `kombu`, `soy sauce` not `shoyu`, `rice wine` not `sake`). Local names go in the recipe's AKA line.
* **Specific cuts and forms** where it matters for nutrition (`chicken thigh` not `chicken`, `firm tofu` not `tofu`).
* **Bone and skin**: always state them for cuts sold both ways (`bone-in skin-on chicken thigh`, `boneless skinless chicken breast`).
  * Pork belly as the cuisine buys it: `skinless pork belly` for Japanese and Korean (butabara, chashu, samgyeopsal), `skin-on pork belly` for Filipino, Chinese, Thai and Vietnamese. If a line says neither, the matcher reads plain `pork belly` as skinless in a Japanese or Korean recipe and skin-on otherwise (13 Nov 2026).
* **As bought, by weight**: a weight is what the cook buys, and only its edible part is counted (`parse_recipe.as_bought`, `recipe_matcher.EDIBLE_SHARE`, by the USDA food matched). Counts need nothing: USDA's "1 thigh" or "1 large" shrimp is already the edible weight.
  * Say `bone-in` for a cut sold both ways (`4 oz bone-in skin-on chicken thigh`, `2 lb bone-in pork shoulder`). Ribs, shanks, oxtail, hocks, pata, knuckles, wings, drumsticks, leg quarters, whole chickens and whole ducks are bone-in unless the line says `boneless`. A sauce, seasoning, marinade, rub, glaze, broth, stock or bouillon named after a cut (`buffalo wing sauce`) is not the cut.
  * Shrimp: plain `shrimp` is peeled. Say `head-on shrimp` or `shell-on shrimp` (also read: `heads on`, `unpeeled`, `in the shell`) when the source buys them so (sinigang na hipon is head-on): 46% and 81% is meat (USDA AH-102).
  * Dried food by weight counts as the fresh food it came from when USDA has only the fresh one (`3 oz dried taro leaves`, laing, is about 19 oz of fresh leaves). Only taro leaves have a factor so far: 6.3, from raw taro leaves' 85.66% water (SR 11520) and dried leaves taken as 10% water, an assumption (25 Nov 2026).
  * Fish by weight (milkfish, tilapia, pompano, snapper, grouper, mackerel, sardines, catfish, carp, trout, sea bass, mullet, galunggong) is the whole fish unless the line says `boneless`, `deboned`, `fillet`, `belly`, `steak`, `flakes`, `canned`, `smoked`, `dried`, `ground`, `minced` or `sashimi` (`1.5 lb milkfish` is about 60% flesh). Only milkfish has a share so far.
* **Raw vs cooked**: ingredients are raw by default. Anything added already cooked says `cooked` (`cooked spaghetti`, `cooked chicken breast`). The matcher uses that word to pick cooked entries. Exception: bare `rice` is read as cooked, so always say which (`1 cup uncooked short grain white rice`, `2 cups cooked rice`).
* **Never "to taste".** Write a fixed amount: the median of the sources; if none gives one, a standard amount (salt: 1/2 tsp per 4 servings; pepper: 1/4 tsp per 4 servings).
* **Zero-calorie lines stay** (water, ice). They show users how much food there is.
* **Serving garnishes** that are mostly not eaten (lemon or lime wedges, herb sprigs) go without a quantity and end in `for serving` or `for garnish`, with **no comma** before it: `lemon wedge for serving`. The parser turns that into a zero-calorie note row; with a comma or a quantity it is counted as food. If the juice is actually used, list the juice with an amount (`1 tsp lemon juice`).

## Measurements

Write amounts the way a home cook would read them. **Never grams**: a user reading "37.5 g onion" can't picture it, and the sources rarely say it.

* **Cups, tbsp, tsp** for liquids, grains, cooked starches, flours, sugars, sauces, pastes, and chopped, sliced or grated produce (`1/2 cup chopped onion`, `2 tbsp sugar`).
* **Counts** (whole, piece, clove, stalk, sheet, slice, fillet, chop, thigh, drumstick, leaf, block) for anything naturally counted, with size where it varies (`1 large onion`, `2 whole medium tomato`). Without a size the matcher assumes medium. The cut can follow the food (`2 boneless pork loin chop`, `2 bread slice`); it is still the unit.
* **Leafy greens sold by the bunch** by the bunch (`1 bunch spinach`), not oz or cups, when the database food has a `bunch` portion (raw spinach's is 340 g; in cups it read as "11 cups"). Without one, use the usual units.
* **Meat** by count or by the cup first, a weight only when the food has neither (Arianna, 25 Nov 2026: users can't estimate a weight). What a line shows is what it is: the food's name, unit and calories come from one USDA row.
  * A raw count is the raw row's own count (`6 bone-in skin-on chicken thigh`, `4 boneless pork loin chop`, `1 Italian sausage`).
  * Meat served in pieces from a pot (braises, stews, soups) is the cooked meat as eaten, by FNDDS's cooked row's cup or count, and the line says `cooked` (or the cooking word): `4.75 cup cooked pork belly`, `5.25 cup cooked beef stew meat`, `6 stewed skin-on chicken thigh`. Without the word the matcher reads a cup of meat as raw. Convert the bought weight with the cooked row's own "1 oz yields" (20 g cooked from 1 oz raw, 0.705 for most FNDDS meat), the bone share left out first, then divide by its cup (135 g; ground meat 125 g) or piece (medium thigh 90 g). 2 lb raw belly is 4.75 cups. Add the drippings that stay in the dish (Drippings, below).
  * Fried meat stays raw (raw count, else weight): the oil and coating rates are a share of the raw edible weight.
  * By weight when no row has a count or cup that fits: `1.5 lb bone-in beef shank` (bulalo), milkfish, pork liver, pancetta.
  * Shrimp counted (`16 large shrimp`, tempura) is FNDDS's boiled shrimp by its piece weight (large/jumbo 15 g as eaten, about 17.5 g raw); the batter and oil rates take the raw weight. Shrimp by weight (`8 oz shrimp`) keeps the raw row. The raw rows' own "large" is 7 g, half a store's large shrimp (16 Nov 2026).
* **Packaged items** by the package (`1 packet tamarind soup mix`, `4 block boxed Japanese curry roux`).
* Sources disagree on units → use the unit most of them use. The ratios still come from all three.
* A source gives both metric and US amounts → use the US/household one. A source gives only grams → prefer another source that doesn't.
* Fractions (`1/2`, `1 3/4`) and decimals (`0.5`) both parse. Use whichever reads naturally.

### Cooked starches

Pasta, rice and noodles are listed **cooked, in cups**, so lookups hit the cooked entries (`1.5 cup cooked spaghetti`, `1 cup cooked long grain white rice`). Never dry weight.

* Name the cooked form and type: `cooked spaghetti`, `cooked elbow macaroni`, `cooked short grain white rice`, `cooked glutinous rice`, `cooked rice vermicelli`.
* **Exception: pasta shapes USDA doesn't list cooked.** USDA has cooked spaghetti, penne, farfalle (bow tie), rotini (fusilli), shells, elbow macaroni and lasagna noodles (the `food_aliases` table). Any other shape (linguine, fettuccine, bucatini, ziti, rigatoni, ditalini, orzo, acini di pepe) is listed **uncooked by weight, as the sources give it** (`12 oz uncooked linguine`): it matches the packaged dry pasta and its label weight. Written in cooked cups anyway, it is converted to dry pasta at 2 oz per cup and flagged in the output.
* Converting a dry amount from a source: long pasta 1 cup cooked ≈ 2 oz dry; dried wheat pasta cooked weight ≈ 2.35 × dry.
* Use the sources' amount: when a source gives one (grams, cups, or an uncooked weight), convert it to cooked cups and use it. Only when none gives an amount, use the typical portions: side = 1 cup cooked; main plate = 1.5 cups cooked.
* **Exception:** when the starch cooks inside the dish and absorbs its liquid (arroz caldo, champorado, biko, risotto, soups with pasta cooked in the broth), list it uncooked by volume (`1 cup uncooked glutinous rice`) together with the liquid.
* **Exception:** noodles sold in single-serving packs (frozen or fresh udon, and others where the sources count packs) are listed by the pack, as the sources do (`2 pack frozen udon noodles`), not in cooked cups.

## Pinned foods (write as regular ingredients)

These are matched straight to one known-good food in the database. Write them as **regular ingredients with real quantities**, never build them from scratch, and never create recipe blocks for them:

* teriyaki sauce
* gyoza dipping sauce
* tonkatsu sauce
* ponzu sauce
* tempura dipping sauce
* unagi sauce
* okonomiyaki sauce
* sesame sauce
* tonkotsu broth
* red bean paste — write `red bean paste`, not `anko`; also use it for sweetened red beans (e.g. in halo-halo)
* saba banana — the Filipino cooking banana (banana cue, turon, nilaga): write `saba banana` by count (`12 saba banana`), not `plantain`; it is USDA's extra-small banana (81 g), the closest whole-fruit portion USDA has; plantain's smallest whole is 180 g. Diced or by the cup it stays `diced plantain`.
* dashi powder — instant dashi powder, matched to FDC 2381716 (Traditional Umami Dashi Soup Base & Seasoning). Its label: 8 g powder per 2 cups water, so **1 tsp (4 g) per 1 cup water**. Write it as `dashi powder` (not hondashi or granules), and only inside the Dashi Stock block; dishes use `dashi stock`.

## Store-bought ingredients

Use the store form where home cooks normally do:

* Japanese curry → `boxed Japanese curry roux`, in blocks (not homemade roux).
* Dashi → the Dashi Stock base template, made from `dashi powder` (FDC 2381716, 1 tsp = 4 g per cup of water, from its label), never kelp and bonito flakes (they are strained out):

  ```
  Dashi Stock
  AKA: Dashi", "Dashi broth
  Servings: 4
  Serving size: 1 cup
  4 cup water
  4 tsp dashi powder
  SOURCE: url1, url2, url3
  ```

  Recipes use it like any ingredient: `1.5 cup dashi stock`.
* Filipino → packets and jars: tamarind soup mix, peanut butter (kare-kare), sauteed shrimp paste, banana ketchup, liver spread.
* Store items that match nothing, even in the branded database, are written normally and left to fall through. Do not invent substitutes to force a match.

## Base templates

A base template is a component other recipes use: a broth, sauce, batter, glaze, or prepared protein (Dashi Stock, Chashu Pork, Tempura Batter).

### When to make one — they are the exception

Check these in order and stop at the first that applies:

1. **It's a pinned food** (list above) **or exists as a database food.** If USDA or the branded database has the finished food, list it as a regular ingredient with a real quantity (`2 tbsp red bean paste`, `3 tbsp purple yam jam`, `1 slice caramel flan`). Use the common English name, specific enough to match (`purple yam jam`, not `ube halaya`; `caramel flan`, not `flan`). Check fdc.nal.usda.gov when unsure. A close generic entry beats a homemade template.
2. **It's single-prep.** Slicing, grating, or mixing into the dish stays as regular ingredient lines.
3. **It's used by only one recipe.** A multi-step component used once (a sauce, a filling, a topping) goes inside that recipe as a `--Section` with its raw ingredients.
4. **Only now, make a base template.** It must be multi-step (marinating, braising, simmering, curing, fermenting, frying then simmering), have no database entry, AND be used by 2 or more recipes in the file (or be something people log on its own, like a cured meat or a condiment sauce).

### Defining one

* `Servings:` is how many serving-size amounts the batch makes.
* `Serving size:` is one serving in the unit people measure it by: a volume (`1 cup`, `2 tbsp`) for liquids, sauces and batters; a count (`1 slice`, `1 whole`, `1 piece`) for proteins and eggs. Required.
* The AKA line lists every name a recipe might use for it (`AKA: Dashi", "Dashi broth`).
* It appears in the file before any recipe that uses it.

### Using one

Write it as a **normal ingredient line**, by its exact name or an AKA, in the same kind of unit as its serving size: `1.5 cup dashi stock`, `2 tbsp dashi stock`, `2 slice braised pork belly`, `1 whole ramen egg`. The parser recognises the name and adds the template's ingredients to the recipe as their own section, scaled to the amount.

* Amounts are what the whole recipe uses; the parser divides by Servings.
* When two cuisines each have a base template with that name (two "Chicken Stock"s), a recipe gets its own cuisine's; another cuisine's is used only when its own has none.
* Volume converts to volume and counts to counts. Never cross them (NOT `1 cup braised pork belly` when the serving size is `1 slice`).
* Never write slugs (`0.375 dashi_stock`) or fractions of a batch.

## Absorbed amounts

For anything cooked in a liquid or fat that is mostly discarded, list only what stays in the food. Basis is **percent of the raw food's edible weight**: estimate the food's weight without bone, head or shell (a bone-in thigh counts its meat and skin, as its calories do), apply the percentage, then write the result in tbsp/tsp.

### Frying oil (`--Absorbed oil`)

<!-- fry_types:start (sync_fry_rates.py writes this table) -->
| Method and food | Absorbed oil (% of the raw food's edible weight) |
|---|---|
| Fatty cuts, unbreaded, deep- or pan-fried (pork belly, pata, skin-on cuts; they lose fat) | 0% |
| Deep-fried, thick starchy pieces (whole plantain, thick-cut potato) | 5% |
| Deep-fried, unbreaded lean meat, fish, tofu | 5% |
| Deep-fried, starch- or flour-dusted meat and poultry, skinless (skinless chicken karaage) | 4.3% |
| Deep-fried, dry starch-dusted tofu, fish and seafood (agedashi tofu, calamari) | 8% |
| Pan-fried fish, unbreaded | 8% |
| Deep-fried, wrapper-enclosed (spring rolls, turon, fried gyoza) | 8% |
| Deep-fried, unbreaded vegetables (su-age eggplant, shishito, mushrooms) | 10% |
| Deep-fried, breaded (panko, breadcrumbs) | 12% |
| Deep-fried, thin starchy slices (chips) | 13% |
| Deep-fried, wet-battered (tempura, kwek-kwek) | 15% |
<!-- fry_types:end -->

Sautés, stir-fries, stews and braises: list **all** the oil — it stays in the dish.

Coated skin-on chicken (karaage, Southern fried chicken) keeps **no** frying oil: list no `--Absorbed oil` section. MEXT 2020 Table 13 weighed skin-on thigh karaage at −0.7 g fat per 100 g raw, coating included (the skin's rendered fat outweighs what the coating takes up); skinless thigh gained 4.3 g, which is the dusted meat rate (skinless meat and poultry, dusted or dredged; tofu, fish and seafood stay at 8%). Since 25 Nov 2026 (Arianna), in recipes and Convert recipe alike.

Battered, breaded or dusted food takes the rate on the food alone, not the food plus its coating: nobody knows how much batter clings (`16 large shrimp`, 112 g, wet-battered at 15% is 17 g, `1.25 tbsp`). The coating's own calories are its own lines.

These rates are fixed. Use them as they are; never change a rate or add a row while writing recipes. Changing one is Arianna's call.

The rates have one copy: the app project's `fry_types` table (blobbapp migration `20261028120000_create_fry_types.sql`). The table above is written from it by `sync_fry_rates.py`, never by hand; the worker reads it (`fry_rates.py`) and sends it to the app's editor, and blobb.app/sources is built from it. To change a rate, change the table, then run `sync_fry_rates.py` and rebuild the site. Sources for every rate: `ABSORPTION_SOURCES.md`.

Convert recipe applies these rates to "oil for frying" lines as fry types, on the fried food's edible weight: wrapped when there's a wrapper (lumpia, spring roll, egg roll, wonton, gyoza; the whole roll, wrapper and filling), then breaded, battered, starch-dusted (dusted meat when everything fried is skinless meat or poultry, dusted or dredged), else unbreaded (lean meat, fish, tofu), unbreaded veg, or thick-cut (starchy pieces, bananas). Meat, fish and tofu are what's fried when there are any; otherwise the starchy food and the vegetables are fried together (vegetable tempura's sweet potato, kabocha and eggplant all take the batter rate). Unbreaded, a mix of starchy food and vegetables is unbreaded veg: watery vegetables keep about twice the oil. Unbreaded fish in oil "for pan-frying" or "shallow frying" is pan-fried fish; unbreaded fatty or skin-on cuts start at no oil, and so does skin-on chicken that's dusted or dredged (flour, starch or buttermilk, not a tempura or beer batter). Thin-sliced and fatty cut are picked by the user. The user can change the type (any of the table's) and the rows it is a share of in the app.

### Coating (flour, egg wash, crumbs)

Coating set out in a bowl is mostly left there. List only what sticks: the rate × the raw food's edible weight, in tbsp/tsp (flour 7.8 g a tbsp, panko 3.4 g a tbsp, a large egg 50 g). Write the lines in the main ingredient list, not a section.

| Coating step | Stays on the food (% of the raw food's edible weight) |
|---|---|
| Flour before egg (breaded) | 3.5% |
| Egg wash | 9% |
| Dry breadcrumbs or panko | 9.5% |
| Flour or starch on a dry surface | 3.5% |
| Flour or starch on a wet surface (marinated, buttermilk-soaked: karaage, Southern fried chicken) | 15% |
| Wet batter (tempura, kwek-kwek): its flour and starch | 11% |

A coating never counts more per gram of food than the most any of the recipe's sources sets out: karaage's sources set out 5–11% (Tasting Table: 3 tbsp flour and 3 tbsp potato starch for 1 lb thighs), so it lists 11%, not 15% (25 Nov 2026, Arianna). The liquid the food soaked in follows the marinade rule below. For a wet batter, scale its egg, water and seasoning by the same share as its flour (`16 large shrimp`, 112 g: 1.5 tbsp flour, 1/6 egg, 1.5 tbsp water). These rates are fixed: use them as they are; changing one is Arianna's call. Sources: `ABSORPTION_SOURCES.md`, "Coatings".

### Marinades (`--Absorbed marinade`)

| Situation | What to list |
|---|---|
| Marinade drained off, meat grilled or fried | 5% of raw meat weight in marinade, split across its ingredients by their ratio |
| Same, thin slices (tapa, bulgogi, yakiniku) | 8% of raw meat weight |
| Marinade cooked down with the meat or used as basting/sauce (adobo, bistek, tocino, teriyaki glaze) | The full marinade amount, no section needed |

### Drippings (`--Drippings`)

FNDDS's cooked meat is counted as eaten with its drippings gone: 2 lb of belly is 3,490 kcal raw but 2,590 as `4.75 cup cooked pork belly`. When the dish keeps that fat (it stays in the sauce or broth), list it as `animal fat or drippings` (FNDDS "Animal fat or drippings", 12 g a tbsp, 101 kcal) in a `--Drippings` section: the raw meat's calories less the cooked row's, times the share that stays, ÷ 101, in tbsp.

* The share comes from the recipe's sources, as the frying oil does. All of it when they keep the fat (no draining, no skimming). Half when they split or only skim the extra fat. None when they drain it, pour it off or grill it away.
* Pilot dishes (26 Nov 2026): adobo all (Panlasang Pinoy and Pepper.ph keep it), 9 tbsp for 4; caldereta half (Nora skims the extra fat, Bite My Bun keeps it), 3.25 tbsp for 6; tinola all (Panlasang Pinoy and Nora keep it), 4.25 tbsp for 6.
* Raw meat by weight or raw count never has drippings: its raw calories already include the fat.
* Rolled out 26 Nov 2026 to the Filipino, Japanese and Italian braises, soups and stir-fries (32 templates). Half for dinuguan, sinigang, batchoy, bolognese, sotanghon and arroz caldo; none for chashu (its slices are the cooked belly, 21 from 2 lb). Pork shoulder's loss is measured from SR's raw Boston butt (186 kcal/100 g). Under 1/4 tbsp is left out (chawanmushi). Kare-kare's oxtail is in cooked cups with no drippings: USDA has no raw oxtail to measure the loss from.
* American, 27 Nov 2026 (8 templates): all for beef stew, chili (two of three keep it), pot roast, jambalaya, chicken noodle soup and pot pie; half for pulled pork (Spend With Pennies skims, RecipeTin says much is discarded); none for sloppy joes (Taste of Home and Spend With Pennies drain).
* Still by weight: bistek (pan-fried), osso buco (SR's 187 g braised cross cut makes 4 shanks read as 3), ribeye (gyudon, nikujaga) and pork loin (ginger pork), which have no cooked row that matches.

### Brines and pickles (`--Absorbed brine`)

Vegetables equilibrate with the brine. List the brine solutes (sugar, salt, vinegar) scaled by `vegetable water ÷ (vegetable water + brine liquid)`, where vegetable water ≈ 90% of the vegetables' weight. Typically 40–55%.

### Boiling and blanching

Salt in pasta or blanching water is not listed. Aromatics boiled and discarded (bay leaves, peppercorns in a stock) are listed; their calories are negligible either way.

## Serving sizes

As small as practically usable for tracking:

* Food that comes in pieces (gyoza, mochi, lumpia): 1 serving = 1 piece
* Skewered food (yakitori, dango, pork barbecue, banana cue): 1 serving = 1 skewer
* How much goes into one piece, skewer or bowl comes from the sources: grams or cups per piece, or the batch ÷ its stated yield. A source that gives no yield doesn't count towards that amount; say so in the chat. (21 Oct 2026: nigiri had 35 g of rice a piece from weak sources; Kikkoman, Pinch and Swirl and Great British Chefs agree on about 15 g.)
* Sauces, pastes, glazes: 1 serving = the smallest amount typically used in one dish
* Bowls/plates for one person: `Servings: 1`
* Batch recipes (a pot of curry for 4): `Servings: 4`

## Separate recipe blocks

* Distinct fillings → separate blocks (Salmon Onigiri, Pickled Plum Onigiri, Tuna Mayo Onigiri).
* Distinct common proteins → separate blocks (Chicken Adobo, Pork Adobo, Water Spinach Adobo).

## Ordering

All base templates (sauces, batters, pastes, broths, glazes, cured or prepared proteins, and any dish referenced by another dish) go at the top, before any recipe that references them. Then: soups → mains → rice dishes → sides → noodles → desserts → drinks.

## Accuracy

Use commonly known ratios; do not reproduce any published recipe verbatim. Compare ratios across sources for realism. The SOURCE line must reflect the pages actually consulted.

## Calorie reference

Every recipe gets an outside calorie figure in `calorie_references.json`, keyed by its ID. The matcher checks each template against it after every run (`check_template_calories.py`) and lists the ones more than 13% and 30 kcal off (20% until 25 Nov 2026). A new recipe without one is listed too.

* **kcal**: calories per serving printed on one of the recipe's SOURCE pages (its nutrition box), **normalised to our serving**: per piece, per skewer, per ½ cup, or the batch ÷ our `Servings:`, using the page's own yield. If no source prints one, use another real recipe page for the dish that does (the same source rules apply). Never estimate calories yourself.
* **url**: the page the figure is from. **basis**: one line on how it was normalised ("447 per serving of 8, 6 pieces each").
* **status**: `ok` for a printed figure divided to our serving (by the page's own yield, or the same batch cut into our pieces): the only independent check. `recipe_match` when the figure is the page's own amounts run through our rows (its printed figure doesn't add up), or a printed figure rescaled to our amount of the main ingredient: it checks our amounts, not our calorie data, since both sides use the same rows; the check counts it apart (Arianna, 25 Nov 2026). Prefer an `ok` reference whenever one adds up. `serving_differs` when the page's serving can't be turned into ours; `not_comparable` when the figure can't be right or isn't independent, with the reason in **note**; `none` when no page gives one.
* Treat a printed figure as suspect when it is impossible for its own ingredients (40 kcal for 1 lb of fish per 4, 4,217 per serving), is a whole batch labelled per serving, or plainly comes from old USDA data we have replaced. Blog nutrition boxes are worked out by a plugin from USDA data: Panlasang Pinoy's pork adobo (1,211) and two sinigang na baboy pages match USDA's old 53%-fat pork belly, which the templates no longer use (13 Nov 2026).
* When the check flags a template, find the cause line by line before importing: a wrong food, amount, unit, portion, raw vs cooked, absorbed oil, servings, or a reference that isn't comparable. Write the cause in **note**. Fix only a real error; recipe amounts and servings are Arianna's call.

Example:

```json
"takoyaki_": {"kcal": 50, "status": "ok",
  "url": "https://japan.recipetineats.com/wprm_print/takoyaki-recipe-octopus-balls",
  "basis": "per ball", "note": null}
```

## Self-check before finishing

* Every base template has `Serving size:` and an AKA line with the names recipes use for it.
* Every use of a base template comes after its definition, uses its exact name or an AKA, and is in the same kind of unit as its serving size.
* No slugs, no fractions of a batch.
* No pinned food is built from scratch or given its own block.
* No grams, no cups of raw meat (cooked meat by the cup says `cooked`), no dry pasta/rice/noodles (except the cooked-in-dish exception), no bare `rice`.
* No "to taste", no non-Latin script in AKA, no commas inside URLs, exactly 3 URLs per SOURCE, and every URL opened and loading.
* Every ID is unique across all recipe files, not just this one.
* Every new recipe has an entry in `calorie_references.json`, normalised to its serving.
* Exactly 3 blank lines between blocks.
