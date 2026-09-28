# Recipe template rules

Read this before generating recipe templates or running `parse_recipe.py`.
It is the prompt given to the AI that writes `{cuisine}_recipes.txt`, and the
rules those files must follow. Templates are user-facing: people open them to
check what a meal contains, so every amount must be one they recognise.

---

I'm building recipe templates for a food tracking app called Blobb. Generate a `.txt` file in the exact format below.
Output filename: `{cuisine}_recipes.txt`
Cuisine: (specify per run)
Include: mains, sides, soups, rice dishes, noodles, desserts, drinks, and any base components needed (sauces, batters, pastes, broths, glazes, marinades, prepared proteins, and compound ingredients that require their own cooking steps — e.g. chashu pork, braised pork belly, ajitsuke tamago)

## Research requirement

For EVERY recipe, research at least 3 real recipe sources before writing it. Cross-reference ingredient ratios across sources and synthesize a realistic composite. Each recipe must include a `SOURCE:` line at the end listing the actual URLs you consulted. Do not generate source URLs after writing the recipe — the sources must inform the ratios, not be attached post-hoc.

## Format rules

* `Category: X` at the top of the file
* 3 blank lines between every recipe block
* Each recipe block:

```
Recipe Name
AKA: First alternate name", "Second name", "Third name
Servings: N
ingredient lines
SOURCE: url1, url2, url3
```

### AKA rules

* Zero alternate names → omit the `AKA:` line entirely
* Single AKA → no quotes (e.g. `AKA: Beef bowl`)
* Two or more AKA → no opening quote on first, no closing quote on last, `", "` between each (e.g. `AKA: Beef bowl", "Gyudon`)
* Use romanized local names only — NO kanji, kana, hangul, or other non-Latin script in AKA lines
* English name is always the primary recipe name; romanized local name goes in AKA

### Ingredient lines

Format: `qty unit ingredient` (e.g. `1 cup glutinous rice flour`, `3 tbsp soy sauce`, `2 whole egg`)

* Use **English ingredient names**, not local-language names (e.g. `green onion` not `negi`, `kelp` not `kombu`, `soy sauce` not `shoyu`, `rice wine` not `sake`). Place the local name in the AKA line of the recipe if useful, but ingredient lines must use the standard English term so nutrition lookups succeed.
* Use specific cuts and forms where it matters for nutrition (e.g. `chicken thigh` not `chicken`, `firm tofu` not `tofu`, `short grain white rice` not `rice`)
* **Serving garnishes** that are mostly not eaten (lemon or lime wedges, herb sprigs) go without a quantity and end in `for serving` or `for garnish`, with **no comma** before it: `lemon wedge for serving`. The parser turns that into a note row with no calories; with a comma (`lemon wedge, for serving`) or a quantity (`1 lemon wedge`) it is counted as food. If the recipe actually uses the juice, list the juice with an amount instead (e.g. `1 tsp lemon juice`).

### Section headers

Use `--Section name` for within-recipe sections (e.g. `--Filling`, `--Absorbed oil`, `--Serving`).

### SOURCE line

Every recipe ends with a `SOURCE:` line containing 3 comma-separated URLs of the actual recipe pages you consulted for ingredient ratios. The parser skips these lines — they are metadata, not ingredients.

## Sub-template system

### References

Sub-template references use the format: `qty slugified_template_id`

The slug is the primary recipe name lowercased with spaces replaced by underscores (e.g. "Dashi Stock" → `dashi_stock`, "Soy Sauce Ramen Base" → `soy_sauce_ramen_base`).

**The `qty` is the fraction of the full batch used by the entire recipe** (not per serving). The parser divides by servings automatically.

Example: Dashi Stock makes 4 cups (Servings: 4). Shoyu Ramen (Servings: 1) needs 1 3/4 cups of dashi. 1.75 / 4 = 0.4375. Write: `0.4375 dashi_stock`.

Example: Pork Miso Soup (Servings: 4) needs 4 cups of dashi — a full batch. Write: `1 dashi_stock`.

The referenced template must appear earlier in the file.

### Decision rule

If an ingredient requires its own multi-step preparation (marinating, braising, simmering, fermenting, frying then simmering, etc.), it **must** be its own template and referenced as a sub-template fraction — never inlined as raw ingredients, and never written as `qty unit slug_name` (e.g. do NOT write `1 3/4 cups dashi_stock`; write `0.4375 dashi_stock`).

Single-prep ingredients (slicing, grating, mixing into the dish directly) stay as regular ingredient lines.

### Fraction math

To calculate the fraction: `amount_recipe_needs / total_batch_yield`.

For liquid-based templates, total batch yield ≈ sum of liquid ingredients. For paste/solid templates, total yield ≈ sum of all ingredients. Convert to one unit for this sum only (e.g. everything to cups); the ingredient lines keep the units the sources use.

Verify per-serving amounts are realistic when dividing.

## DB templates (do NOT redefine)

The following templates already exist in the app's database. Reference them as **regular ingredients with real quantities** (e.g. `1 tbsp tonkatsu sauce`), NOT as sub-template fractions. Do not create recipe blocks for these:

* teriyaki sauce
* gyoza dipping sauce
* tonkatsu sauce
* ponzu sauce
* tempura dipping sauce
* unagi sauce
* okonomiyaki sauce
* sesame sauce
* tonkotsu broth
* red bean paste (referenced as `red bean paste` in ingredient lines, not `anko`)

## Serving sizes

Servings must be realistic and as small as practically usable for tracking:

* Food that comes in pieces (gyoza, mochi, daifuku): 1 serving = 1 piece
* Sauces, pastes, glazes: 1 serving = the smallest amount typically used in one dish
* Bowls/plates meant for one person: `Servings: 1`
* Batch recipes (e.g. a pot of curry for 4): `Servings: 4`

## Absorbed amounts only

For marinades and frying oil, list only the amount absorbed into the food, not the total used:

* **Marinades**: ~25–35% of total marinade is absorbed. Use a `--Absorbed marinade` or `--Absorbed seasoning` section.
* **Deep frying (panko-breaded)**: ~10–15% oil absorption by weight of coating. Use `--Absorbed oil` section.
* **Deep frying (starch-coated)**: ~8–12% oil absorption. Use `--Absorbed oil` section.
* Write the absorbed amount in spoons or cups (e.g. `2 tbsp vegetable oil`), not grams.

Do NOT list the full frying oil bath or full marinade volume.

## Measurements

Write amounts in the units the source recipes use. **Never convert to grams**:
a user reading "37.5 g onion" can't picture it, and the sources rarely say it.

* Counts, cups, spoons, oz/lb, cooked or uncooked: whatever the sources give
  (`1 medium onion`, `2 chicken thighs`, `1 cup cooked rice`, `8 oz ground beef`).
* Sources disagree on units → use the unit most of them use. The ratios still
  come from all three.
* A source lists both metric and US amounts → use the US/household one.
* A source gives only grams → prefer another source that doesn't. Use grams
  only when no good source gives anything else.
* Rice and grains: say which (`1 cup uncooked short grain white rice`,
  `2 cups cooked rice`). The matcher reads bare "rice" as cooked.
* Counted produce: keep the size the source gives (`1 large onion`). Without
  one, the matcher assumes medium.
* `whole` / `piece` / `clove` / `stalk` / `sheet` / `slice` for countable items.

## Boxed/prepared ingredients

Some ingredients should use their prepared/boxed form rather than being made from scratch:

* Japanese Curry → use boxed Japanese curry roux, in the blocks or fraction of a box the sources give (e.g. `4 block boxed Japanese curry roux`), not homemade roux
* Dashi Stock → instant: `dashi powder` at 1 tsp per 1 cup water, i.e. `4 cups water` + `4 tsp dashi powder` for the 4-cup batch. Not kelp and bonito flakes, which are strained out and would be counted as eaten.

## Separate recipes for different fillings

Items with distinct fillings should be separate recipe blocks, not one recipe with variations:

* Onigiri → separate recipes for each filling (e.g. Salmon Onigiri, Pickled Plum Onigiri, Tuna Mayo Onigiri)

## Ordering rule

All base templates (sauces, batters, pastes, broths, glazes, and prepared sub-components) must appear at the top of the file, before any composite recipes that reference them. Then: soups → mains → rice dishes → sides → noodles → desserts → drinks.

## Accuracy

Use commonly known ratios and proportions; do not reproduce any published recipe verbatim. Compare ingredient ratios against multiple sources for realism. The SOURCE line must reflect the actual pages you consulted — not pages found after writing.
