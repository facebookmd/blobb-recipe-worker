Blobb recipe templates
======================

Turns recipe text into Blobb meal templates: each ingredient matched to a
food in Supabase, with an amount and a unit. Two ways in, one matcher:

  * Batch: recipe files -> parse_recipe.py -> templates_output.xlsx/.csv ->
    the import tool -> the curated templates everyone sees in the app.
  * In-app: "Convert recipe" posts pasted text to app.py on Cloud Run,
    which returns one template to the app.

Before writing recipe files, read RECIPE_RULES.md: it is the prompt for the
AI that writes {cuisine}_recipes.txt, and the rules those files must follow.


FILES
-----
  RECIPE_RULES.md          Rules and prompt for writing recipe files.
  recipes/                 The recipe files (japanese_recipes.txt): the
                           source of every curated template, IDs included.
  parse_recipe.py          Reads recipe text into recipes.csv, then runs the
                           matcher. The batch command.
  recipe_matcher.py        Matches ingredients to foods, picks portions and
                           amounts, writes templates_output.xlsx and .csv.
  template_refs.py         Base templates used by name inside other recipes.
  supabase_food_source.py  Reads foods and portions from the USDA Supabase
                           project (cached on disk).
  boosts.json              Hand-written matching rules (see FIXING A MATCH).
  app.py                   The Cloud Run server behind "Convert recipe".
  auth.py                  Who may call it (signed-in app users), how often.
  Dockerfile, .dockerignore, requirements.txt
                           How Cloud Build packages the server.
  requirements-dev.txt     Extra packages for the tests.
  test_*.py                Tests; see TESTS.


SETUP
-----
  Python 3.10+, then:  pip install -r requirements-dev.txt openpyxl
  SUPABASE_ANON_KEY      The USDA project's key (Blobb App/.env). Required.
  SUPABASE_URL           Optional; defaults to the USDA project.

The server also reads, on Cloud Run:
  APP_SUPABASE_KEY       The app project's publishable key, so pasted recipes
                         can use published base templates. Without it, a line
                         naming one is matched as a food.
  APP_SUPABASE_URL       Optional; defaults to the app project.


BATCH RUN
---------
From this folder, with SUPABASE_ANON_KEY set:

    python3 parse_recipe.py recipes/japanese_recipes.txt --yes --forceall

  * Several files in one run: list them, files that define base templates
    first. A file holds many recipes, separated by 3 blank lines or ---.
  * --yes skips the per-recipe preview. Without it, each recipe is shown
    first: Enter confirms, s skips, d <n> drops a row, e <n> edits one,
    r renames, q quits.
  * --forceall starts the output fresh; without it, recipes already in
    templates_output.xlsx are kept and only new ones run (--force re-runs
    the ones in this file).
  * --parse-only writes recipes.csv and stops. --threshold (default 0.45)
    is the lowest match score accepted.

Output: templates_output.xlsx (to review) and templates_output.csv (to
import), in the folder you ran from.

A Supabase request that still fails after one retry stops the run, and
the output files are left as they were: run it again. (Taken as no
results, a failed lookup quietly changed amounts.)

Then import into the app project, from blobbapp/:

    python3 tool/csv_templates_to_supabase_migration.py \
        --input ../templates/templates_output.csv \
        --output supabase/migrations/<timestamp>_import_templates.sql

It replaces every curated template (no submitted_by; people's own templates
are never touched) and refuses to write anything if an ingredient has no
food. Review the SQL, then: supabase db push --dry-run, supabase db push.


RECIPE FILE FORMAT
------------------
RECIPE_RULES.md has the full rules. In short:

    Category: Japanese



    Dashi Stock
    ID: dashi_stock
    AKA: Dashi", "Dashi broth
    Servings: 4
    Serving size: 1 cup
    4 cup water
    4 tsp dashi powder
    SOURCE: url1, url2, url3

  * ID: is the template's id, what share links (blobb.app/?dish=<id>) and
    saved meals point at. It stays when the title changes, so rename by
    editing the title line only. Lowercase letters, digits, _ and -. A new
    recipe may leave it out: the id is then made from the title ("Miso
    Soup" -> miso_soup; one-word titles get a trailing _, "Gyoza" ->
    gyoza_); add that ID: line before its first import. Two recipes with one ID stop the batch run, and the
    import tool, naming both.
  * Amounts are for the whole recipe; the parser divides by Servings.
  * --Section lines start a section (--Sauce, --Absorbed oil).
  * "to taste" and "lemon wedge for serving" become note rows, with no
    calories, left out of the saved template.
  * The parser also copes with pasted web recipes: bullets, checkboxes,
    unicode fractions, ranges (averaged), "150g", "(note 1)".


BASE TEMPLATES
--------------
A recipe other recipes use (Dashi Stock, Braised Pork Belly) has a
"Serving size:" line. Another recipe uses it like any ingredient, by name or
AKA, in that kind of unit: "1.5 cup dashi stock". template_refs.py copies
its ingredients in as a "Dashi Stock" section, scaled by amount / serving
size (1.5 servings here). Copies, not links: editing Dashi Stock later
doesn't change recipes already made from it.

  * Batch runs use templates earlier in the run, or from earlier runs in
    templates_output.xlsx. The in-app server uses curated published ones.
  * A line in the wrong kind of unit ("1 cup braised pork belly" when it is
    measured in slices), a template with no Serving size, or one used
    before its block stops a batch run with the line named. Close misses
    ("dashi stok") are listed but matched as foods.
  * The old slug form ("0.25 dashi_stock") is refused.


REVIEW SPREADSHEET
------------------
One row per ingredient, a TOTAL row per recipe. Colours:
  White          USDA match
  Light yellow   Branded match
  Light red      Low confidence - check it
  Pink           No match - must fix before importing

Main columns: component_label (as written), matched_food_name, food_id (FDC
id; B_ for branded), portion_amt x portion_description ("1 cup (240 g)"),
calories_kcal per portion, cal_tot, section, notes (score and source, and
flags like "PORTION NOT FOUND, estimated"), unit_label / unit_grams (the
unit exactly, for the import), servings / serving_qty / serving_unit.


FIXING A MATCH
--------------
Fix the cause, then re-run; don't edit the output.

  * Wrong food: pin it in boosts.json,
      {"trigger": "unagi sauce", "fdc_id": "B_1865541", "weight": 0.95}
    or rewrite the search,
      {"trigger": "kangkong", "boost": "swamp cabbage", "weight": 0.6}
    "exclude" skips lines containing a word; "category" limits a rule to a
    cuisine. Rules apply in file order, first match wins.
  * Wrong amount: a portion rule for a unit,
      {"trigger": "dashi powder", "portion_gram_weight": 4.0,
       "portion_label": "1 tsp", "portion_unit": "tsp"}
  * Wrong wording: change the recipe line (RECIPE_RULES.md).

Find FDC ids at fdc.nal.usda.gov or in the Supabase foods table.

Portion rules the matcher follows on its own:
  * Volumes stay in the recipe's unit, worked out from the food's own
    plain volume portions when it lacks that unit (US cups; fine and
    pourable foods only, never "cup, chopped"). Under 1/4 cup reads in
    spoons. A cup of water is 250 ml.
  * Branded foods use their label serving. A label "cup" that isn't
    230-250 ml is the container it's sold in, and never converts.
  * "1 packet" is the label's package weight.
  * A cut after the food is its unit: "2 boneless pork loin chop" counts
    chops, as "2 pork chops" does ("bread slice" too). A count against a
    plain weight portion ("4 oz", no count portion) is one portion each.
  * Curry, kaffir/makrut lime, pandan and banana leaves are note rows (no
    food in the data, about 0 kcal).


TESTS
-----
    .venv/bin/python -m pytest -q

  test_sub_templates.py        Base templates by name, scaling, errors
  test_branded_portions.py     Label servings, packets, container cups
  test_portions.py             Cups for spoon-only foods, water
  test_recipe_unit_volume.py   Volume lines stay in the recipe's unit
  test_units.py                Units sent to the app, count words, leaves
  test_recipe_countable_cut.py Trailing cuts (chop, slice) as the unit
  test_frying_oil.py           Frying oil as the absorbed share, fried rows
  test_matching_fallbacks.py   Search fallbacks, Supabase requests
  test_auth.py                 Sign-in and rate limits
  test_template_ids.py         ID: lines, renames, duplicate ids refused


DEPLOYING THE SERVER
--------------------
Pushing to main deploys: a Cloud Build trigger builds the Dockerfile and
rolls out a new revision of blobb-recipe-worker (project
blobb-recipe-worker, us-central1). Environment variables set on the service
carry over. Check: curl <service url>/health -> {"status":"ok"}.
