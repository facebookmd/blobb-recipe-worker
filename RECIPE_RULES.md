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
* Do NOT use AI-generated wikis, aggregator/Q&A pages, scraped mirror sites, or forum posts.
* URLs must contain no commas or spaces. Percent-encode if needed (space → `%20`).
* Conversion and nutrition references (USDA densities, absorption figures) are cited in the chat response, not on the SOURCE line. SOURCE is for recipe pages only.

## Format

* `Category: X` at the top of the file
* 3 blank lines between every recipe block
* Each recipe block:

```
Recipe Name
AKA: First alternate name", "Second name", "Third name
Servings: N
Serving size: 1 cup
ingredient lines
SOURCE: url1, url2, url3
```

`Serving size:` is required on base templates (see Base templates) and omitted on everything else.

### AKA line

* Zero alternate names → omit the `AKA:` line entirely
* Single AKA → no quotes (`AKA: Beef bowl`)
* Two or more → no opening quote on the first, no closing quote on the last, `", "` between each (`AKA: Beef bowl", "Gyudon`)
* Romanized local names only — NO kanji, kana, hangul, or other non-Latin script. Drop diacritics (`Ragu`, not `Ragù`).
* The English name is always the primary recipe name; the romanized local name goes in AKA.

### Section headers

`--Section name` for sections within a recipe (`--Filling`, `--Sauce`, `--Absorbed oil`, `--Absorbed marinade`, `--Serving`).

### SOURCE line

Every recipe ends with `SOURCE:` and exactly 3 comma-separated URLs. The parser skips this line.

## Ingredient lines

Format: `qty unit ingredient` (`1 cup glutinous rice flour`, `3 tbsp soy sauce`, `2 whole egg`)

* **English names**, not local-language names (`green onion` not `negi`, `kelp` not `kombu`, `soy sauce` not `shoyu`, `rice wine` not `sake`). Local names go in the recipe's AKA line.
* **Specific cuts and forms** where it matters for nutrition (`chicken thigh` not `chicken`, `firm tofu` not `tofu`).
* **Bone and skin**: always state them for cuts sold both ways (`bone-in skin-on chicken thigh`, `boneless skinless chicken breast`).
* **Raw vs cooked**: ingredients are raw by default. Anything added already cooked says `cooked` (`cooked spaghetti`, `cooked chicken breast`). The matcher uses that word to pick cooked entries. Exception: bare `rice` is read as cooked, so always say which (`1 cup uncooked short grain white rice`, `2 cups cooked rice`).
* **Never "to taste".** Write a fixed amount: the median of the sources; if none gives one, a standard amount (salt: 1/2 tsp per 4 servings; pepper: 1/4 tsp per 4 servings).
* **Zero-calorie lines stay** (water, ice). They show users how much food there is.
* **Serving garnishes** that are mostly not eaten (lemon or lime wedges, herb sprigs) go without a quantity and end in `for serving` or `for garnish`, with **no comma** before it: `lemon wedge for serving`. The parser turns that into a zero-calorie note row; with a comma or a quantity it is counted as food. If the juice is actually used, list the juice with an amount (`1 tsp lemon juice`).

## Measurements

Write amounts the way a home cook would read them. **Never grams**: a user reading "37.5 g onion" can't picture it, and the sources rarely say it.

* **Cups, tbsp, tsp** for liquids, grains, cooked starches, flours, sugars, sauces, pastes, and chopped, sliced or grated produce (`1/2 cup chopped onion`, `2 tbsp sugar`).
* **Counts** (whole, piece, clove, stalk, sheet, slice, fillet, thigh, drumstick, leaf, block) for anything naturally counted, with size where it varies (`1 large onion`, `2 whole medium tomato`). Without a size the matcher assumes medium.
* **Meat** by count (`2 boneless skinless chicken thigh`) or, when it is sold by weight, **oz or lb** (`8 oz ground beef`, `1.5 lb oxtail`). Never cups of meat: the matcher can't convert them and logs the wrong weight.
* **Packaged items** by the package (`1 packet tamarind soup mix`, `4 block boxed Japanese curry roux`).
* Sources disagree on units → use the unit most of them use. The ratios still come from all three.
* A source gives both metric and US amounts → use the US/household one. A source gives only grams → prefer another source that doesn't.
* Fractions (`1/2`, `1 3/4`) and decimals (`0.5`) both parse. Use whichever reads naturally.

### Cooked starches

Pasta, rice and noodles are listed **cooked, in cups**, so lookups hit the cooked entries (`1.5 cup cooked spaghetti`, `1 cup cooked long grain white rice`). Never dry weight.

* Name the cooked form and type: `cooked spaghetti`, `cooked elbow macaroni`, `cooked short grain white rice`, `cooked glutinous rice`, `cooked rice vermicelli`.
* Converting a dry amount from a source: long pasta 1 cup cooked ≈ 2 oz dry; dried wheat pasta cooked weight ≈ 2.35 × dry.
* Typical portions: side = 1 cup cooked; main plate = 1.5 cups cooked.
* **Exception:** when the starch cooks inside the dish and absorbs its liquid (arroz caldo, champorado, biko, risotto, soups with pasta cooked in the broth), list it uncooked by volume (`1 cup uncooked glutinous rice`) together with the liquid.

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
* Volume converts to volume and counts to counts. Never cross them (NOT `1 cup braised pork belly` when the serving size is `1 slice`).
* Never write slugs (`0.375 dashi_stock`) or fractions of a batch.

## Absorbed amounts

For anything cooked in a liquid or fat that is mostly discarded, list only what stays in the food. Basis is **percent of the raw food's weight**: estimate the food's weight, apply the percentage, then write the result in tbsp/tsp.

### Frying oil (`--Absorbed oil`)

| Method and food | Absorbed oil (% of raw food weight) |
|---|---|
| Deep-fried, breaded (panko, breadcrumbs) | 20% |
| Deep-fried, battered or starch-coated (tempura, karaage, kwek-kwek) | 15% |
| Deep-fried, wrapper-enclosed (spring rolls, turon, fried gyoza) | 12% |
| Deep-fried, unbreaded lean meat, fish, tofu, vegetables | 7% |
| Deep-fried, thick starchy pieces (whole plantain, thick-cut potato) | 5% |
| Deep-fried, thin starchy slices (chips) | 30% |
| Pan-fried fish, unbreaded | 8% |
| Fatty cuts, unbreaded, deep- or pan-fried (pork belly, pata, skin-on cuts) | 0% (they lose fat) |

Sautés, stir-fries, stews and braises: list **all** the oil — it stays in the dish.

### Marinades (`--Absorbed marinade`)

| Situation | What to list |
|---|---|
| Marinade drained off, meat grilled or fried | 5% of raw meat weight in marinade, split across its ingredients by their ratio |
| Same, thin slices (tapa, bulgogi, yakiniku) | 8% of raw meat weight |
| Marinade cooked down with the meat or used as basting/sauce (adobo, bistek, tocino, teriyaki glaze) | The full marinade amount, no section needed |

### Brines and pickles (`--Absorbed brine`)

Vegetables equilibrate with the brine. List the brine solutes (sugar, salt, vinegar) scaled by `vegetable water ÷ (vegetable water + brine liquid)`, where vegetable water ≈ 90% of the vegetables' weight. Typically 40–55%.

### Boiling and blanching

Salt in pasta or blanching water is not listed. Aromatics boiled and discarded (bay leaves, peppercorns in a stock) are listed; their calories are negligible either way.

## Serving sizes

As small as practically usable for tracking:

* Food that comes in pieces (gyoza, mochi, lumpia): 1 serving = 1 piece
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

## Self-check before finishing

* Every base template has `Serving size:` and an AKA line with the names recipes use for it.
* Every use of a base template comes after its definition, uses its exact name or an AKA, and is in the same kind of unit as its serving size.
* No slugs, no fractions of a batch.
* No pinned food is built from scratch or given its own block.
* No grams, no cups of meat, no dry pasta/rice/noodles (except the cooked-in-dish exception), no bare `rice`.
* No "to taste", no non-Latin script in AKA, no commas inside URLs, exactly 3 URLs per SOURCE.
* Exactly 3 blank lines between blocks.
