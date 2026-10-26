Replace the default palettes:
    python woz_palettemod.py replace PaletteName.txt

Add a new palette AFTER the default or last palettes in the list:
    python woz_palettemod.py add PaletteName.txt

Target the file without needing to copy it:
    python woz_palettemod.py add PaletteName.txt --target "path\to\animaleditordata_.xml"

Options:
  --target "path\to\animaleditordata_.xml"      select a directory or the name of the file to edit
  --no-backup                                   no backup of the file is created on the directory

CAREFUL: Whenever you directly edit an "animaleditordata_.xml" file, by default a backup is created in the same location, so I'd recommend getting a first backup of the original file, keeping it somewhere safe, and then continuing with --no-backup if you need to replace / add more.

- Why "palette" and not just "colors"?:
In-game, each page of the paintbox includes 8 colors, and I'm counting the pages as a palette, since they kinda have a theme going (e.g.: warm colors, greens, cold colors, purples)
I'm expecting that the users of this tool keep this in mind and decide to divide their new colors in 8s and create palettes close to how it is in-game.

But you can also add any random color in any random quantity, and the game will take it without complaining. You could even add 10 colors one time, then add 7, then 5, and you'll have the default 40 colors + the 22 new colors you added. In-game, this would add 3 new pages to the paintbox, with the 3rd page having only 6 colors. The missing 2 are simply empty spaces.

That's why I recommend trying to create palettes of 8 colors, so the pages look neat.
Also, it's built this way so you can keep many text files with different colors in them, for whatever reason you may need. There are some example palettes included too.

This website can help organize them better:
https://rapidtoolset.com/en/tool/color-sorter
