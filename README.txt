Blobb Recipe-to-Template Pipeline
===================================
parse_recipe.py  +  recipe_matcher.py


WHAT THIS DOES
--------------
You paste or type a recipe ingredient list into a text file. The scripts
parse it, match every ingredient against your food databases, let you review
and fix the matches interactively, then output three things:

  1. templates_output.xlsx   — human review spreadsheet (always produced)
  2. templates.json          — app-ready JSON  (optional, --export-json)
  3. templates.db            — app-ready SQLite (optional, --export-sqlite)

The JSON and SQLite files are what your Flutter app actually ingests.
The spreadsheet is just for you to catch bad matches before committing them.

Calories are NOT stored in the app exports. The app computes them at
runtime by looking up the food in its local database. This is intentional —
it means portion sizes stay dynamic and the data stays small.


REQUIREMENTS
------------
  Python 3.10+
  openpyxl      →  pip install openpyxl       (for .xlsx output)
  sqlite3       →  built into Python           (for .db output)
  Supabase anon key is optional, but recommended.
  Set SUPABASE_ANON_KEY and optionally SUPABASE_URL to read live food tables.

No other packages needed.


FILES IN THIS FOLDER
---------------------
  parse_recipe.py      Parse freeform recipe text + run the full pipeline
  recipe_matcher.py    Match recipes.csv against food databases
  boosts.json          Your custom fuzzy-match correction rules
  README.txt           This file

You need to supply:
  food_db.csv              Export the blobb_food_database sheet from Google
                           Sheets as CSV. File → Download → Comma-separated.
                           Must include cols A-X (FDC_ID through Energy kcal).

  off_clean_with_ids.csv   Your full Open Food Facts database. Used as a
                           fallback when a food is not found in USDA.
                           If absent, the script still runs (USDA only).

When SUPABASE_ANON_KEY is set, the USDA and branded food lookups come from the
remote Supabase `foods` and `food_portions` tables instead of the local exports
above. OFF still uses the local CSV fallback for now.


NORMAL WORKFLOW
---------------
Step 1 - Write your recipe as a text file (see INPUT FORMAT below).

Step 2 - Run parse_recipe.py:

    python parse_recipe.py adobo.txt

    Multiple files at once:
    python parse_recipe.py adobo.txt sinigang.txt kare_kare.txt

    Multiple recipes in one file - separate them with --- or 3+ blank lines:
    python parse_recipe.py all_recipes.txt

Step 3 - Review the preview table in the terminal. Each recipe is shown
    one at a time. Available commands:
      [Enter]       confirm all rows and move to the next recipe
      s             skip this recipe entirely
      d 3           drop row 3
      e 3           edit row 3 (prompts for qty / unit / name)
      r New Name    rename the recipe
      q             quit without writing anything

Step 4 - The scripts write recipes.csv, run the matcher automatically,
    and produce templates_output.xlsx. Open it to review match quality.

Step 5 - Fix bad matches. Two ways:
      a) Add a rule to boosts.json and re-run (for systematic problems)
      b) Directly edit the food_id / portion_id in the spreadsheet,
         then re-run with --parse-only to regenerate the app exports
         from the corrected recipes.csv

Step 6 - Once satisfied, export for the app:

    python parse_recipe.py adobo.txt \
        --export-json  templates.json \
        --export-sqlite templates.db

    Drop templates.db (or templates.json) into your Flutter project.


USEFUL FLAGS
------------
  --category "Filipino Main"    Tag all recipes in this run with a category
  --yes / -y                    Skip interactive preview, confirm everything
  --parse-only                  Write recipes.csv only, skip matching
  --append                      Add to existing recipes.csv instead of
                                overwriting (auto-enabled for multiple files)
  --threshold 0.45              Minimum match score (default 0.45)
                                Raise to be stricter, lower to get more matches
  --export-json PATH            Also write app-ready JSON
  --export-sqlite PATH          Also write app-ready SQLite

  --db PATH                     Path to food_db.csv (default: food_db.csv)
  --off PATH                    Path to OFF csv (default: off_clean_with_ids.csv)
  --output PATH                 Review spreadsheet path (default: templates_output.xlsx)

All flags work on both parse_recipe.py and recipe_matcher.py.


BUILDING UP THE TEMPLATE SET OVER TIME
---------------------------------------
For a single session (e.g. 10 recipes in one go):

    python parse_recipe.py *.txt --category "Filipino Main" \
        --export-json templates.json --export-sqlite templates.db

To add more recipes later without losing the ones already done:

    python parse_recipe.py new_recipes.txt --append \
        --export-json templates.json --export-sqlite templates.db

--append means:
  - New recipe rows are added to recipes.csv (old rows kept)
  - templates_output.xlsx is regenerated from the full CSV
  - templates.db uses INSERT OR REPLACE, so old rows are preserved
    and any re-matched rows are cleanly updated


INPUT FORMAT
------------
The parser handles almost anything. All of these work:

    * 0.5 lbs __pork belly__ (note 1)
    - [ ] 2 tablespoons soy sauce
    ▢ ½ cup vinegar
    1. 3-4 cloves garlic
    • 150g chicken breast, grilled
    Salt to taste

Supported:
  ▢ / - [ ] / * [ ]   Markdown checkboxes (from Notion, websites, etc.)
  * / - / bullets/numbers  Any list format
  __bold__ / **bold**  Copy-paste formatting markers (inner text is kept)
  (note 1) etc.        Note annotations (stripped entirely)
  ½ ¼ ¾ ⅓ ⅔ ⅛        Unicode fractions
  1/2  1 1/2  3-4      ASCII fractions, mixed numbers, ranges (averaged)
  150g  2tbsp           Number glued directly to unit (no space needed)
  to taste / as needed  Written as a note row, no calories counted

Recipe name detection: the first line that does not look like an ingredient
(no leading number, no unit keyword, 2+ words) becomes the recipe name and
template_id automatically. A file starting with "Chicken Adobo" names itself.


REVIEW SPREADSHEET (templates_output.xlsx)
------------------------------------------
One sheet: templates_output

Columns:
  template_id         Recipe slug (e.g. chicken_adobo)
  template_name       Display name
  other_names         Blank - fill in manually if needed
  category            Category tag
  component_label     Ingredient as you wrote it
  food_id             Matched food ID (FDC_ID for USDA, OFF_xxxxx for OFF)
  portion_id          {food_id}_{index}  e.g. 174277_4
  portion_amt         How many of that portion
  portion_description Portion label and gram weight e.g. "1 cup (255 g)"
  calories_kcal       Kcal for one unit of that portion (plain number)
  cal_tot             =calories_kcal x portion_amt  (live Excel formula)
  sub_template_id     Blank - fill in manually for nested templates
  notes               Match score + source, or "to taste"

Colour coding:
  White               High-confidence USDA match (score >= 0.55)
  Amber (#FFD966)     Low-confidence match (0.45-0.54) - worth checking
  Pale green          Matched from OFF database
  Pink  (#FFB3B3)     No match found - must fix manually

Each recipe ends with a TOTAL row summing cal_tot for that recipe.

To fix a pink or amber row:
  1. Find the correct food_id in food_db.csv (search by Display Name)
  2. Find the right portion_id ({food_id}_{portion index}, starting at 1)
  3. Edit those two cells in the spreadsheet
  4. Re-run the matcher to regenerate the app exports with the fix:
       python recipe_matcher.py --export-sqlite templates.db


MATCHING LOGIC
--------------
For each ingredient:
  1. Strip prep words (chopped, diced, frozen, raw, grilled, etc.)
  2. Apply boost rules - built-in first, then your boosts.json
  3. Score every USDA food by bigram similarity to the cleaned ingredient
  4. If best USDA score < threshold, search OFF database instead
     (OFF uses an inverted index - fast even at 200k rows)
  5. Pick the highest-scoring match above threshold
  6. Select best portion by matching unit keyword to portion label
     (tbsp → "tablespoon", clove → "clove", piece → "medium/large/small")
  7. Derive portion_amt from gram conversion if possible,
     or use qty directly for countable units (piece, clove)

food_id prefix tells the app where to look at runtime:
  No prefix (e.g. 174277)    →  local USDA table (bundled with app)
  OFF_ prefix (e.g. OFF_001) →  OFF cache (fetch from cloud on first use,
                                 then stored locally forever)


UNIT CONVERSIONS
----------------
  oz      x 28.35 g
  lb      x 453.6 g
  tbsp    x 15 g
  tsp     x 5 g
  cup     x 240 g  (default - water, broth, stock)
          x 245 g  (sauce)
          x 134 g  (peas, beans, lentils)
          x 218 g  (oil)
  g / kg / ml   direct
  piece / clove / unit   qty used as portion_amt directly (no gram conversion)


BUILT-IN BOOST RULES
--------------------
These run automatically before your boosts.json:

  soy sauce       → shoyu
  cooking oil     → vegetable oil soybean
  potato          → potatoes flesh and skin raw
  bell pepper     → sweet red pepper raw
  green peas      → peas green frozen unprepared
  onion           → onions raw
  garlic          → garlic raw
  bay leaf        → bay leaf
  chili pepper    → hot red chili pepper
  beef broth      → beef broth canned
  chicken broth   → chicken broth low sodium
  tomato sauce    → tomato sauce canned
  liver spread    → liverwurst spread
  pork bouillon   → beef bouillon cubes dry
  hotdog          → frankfurter meat

To add your own, edit boosts.json:
  [
    { "trigger": "kangkong", "boost": "swamp cabbage", "weight": 0.6 },
    { "trigger": "kesong puti", "boost": "white fresh cheese", "weight": 0.6 }
  ]
  trigger  substring to match in the ingredient name
  boost    alternative search string sent to the matcher instead
  weight   confidence bonus (0.0-1.0); 0.6 is a safe default


APP EXPORT SCHEMA
-----------------
Both --export-json and --export-sqlite use the same data model.

templates
  template_id       TEXT  primary key slug
  template_name     TEXT  display name
  other_names       TEXT  nullable
  category          TEXT  nullable
  sub_template_id   TEXT  nullable

template_components
  component_id      TEXT  "{template_id}_{sort_order}"
  template_id       TEXT  foreign key → templates
  sort_order        INT   display order within the recipe
  component_label   TEXT  ingredient name as written
  food_id           TEXT  nullable (null for "to taste" rows)
  portion_id        TEXT  nullable
  portion_amt       REAL  nullable - default portion count
  notes             TEXT  match score, "to taste", etc.

No calorie values are stored. The app computes them at display time:
  calories = (portion.gramWeight / 100) * food.energyPer100g * component.portionAmt

The user can change portion_id and portion_amt freely in the app.
food_id routing at runtime:
  food_id starts with "OFF_"  →  check local OFF cache; fetch from cloud
                                  on first use, then stored locally forever
  food_id has no prefix       →  look up in local USDA table (always available)
