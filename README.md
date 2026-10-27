# WoZ-Tools
<img width="1280" height="128" alt="image" src="https://github.com/user-attachments/assets/1ddd0c44-6858-4d36-9262-b2da54b5cc90" />

A collection of Python scripts useful for extracting, repacking, and replacing World of Zoo files. With the purpose of opening a new world of modding for the 2009 game.

This project was coded with Claude Sonnet 5.5; BUT throroughly tested, supervised, and requested by a human. I also wrote by hand this readme and set up the Github page myself.

---------------------------------------------------------------------------------------
### Requirements & How-to:
An entire copy of Wii version's 00_Retail folder, and the original PC game. Python3 required at most. Each script contains comments on how to use them, still, copying these here to make things easier.<br />
The sounds and music inside `data\00_Retail\Sound\Soundbanks\00_Retail_Wii` are not necessary; these already come with the retail PC game (and no tool included touches sound files).

### wozconvert.py
Can convert the entire packages from Wii to PC, Big-Endian to Little-Endian. Can handle individual files or folders full of 'em. <br />
This single tool includes `wozpkg`, `wozhkx`, `wozdsc`, `woztpl`, and `wozfix`. Does NOT include `woz_langpkg` as a module.<br />
If you only plan to convert your Wii files, it's recommended to use `--drop-256`.<br />
```
    python wozconvert.py Wii.pkg Out.pkg  [options]
    python wozconvert.py WiiFolder OutFolder  [options]
```
	
*Options:*<br />
```
--hkx DIR          optional: packs folder of already converted .hkx files that take priority, same relative paths
--textures DIR     optional: packs folder of already converted textures (same relative paths, x.dds or x.tga) that take priority
--drop-256         leave out the low-resolution *_256 .tpl/.rlet variants (the PC packages do not have them)
--report FILE      also write the report to a text file
--table FILE       optional: order table (woz_order_table.json) to write entries in the PC files' order
--ref PC.pkg ...   PC packages to learn the PC entry order from (use instead of / in addition to --table)
--save-table FILE  write the order table learned from --ref
```
*Options (for textures):*
```
--dds-mode MODE    rgba (default: uncompressed 32-bit DDS with mipmaps) or dxt1 (lossless DXT1 for CMPR textures, single level)
--no-mips          do not generate mipmaps for uncompressed DDS files
--tga-raw          write the 24-bit colour-layer TGA files uncompressed instead of RLE
--tga-legacy       old behaviour: every TGA as 32-bit uncompressed (colour layers will display gray in-game)
--keep-tpl         do not convert textures; leave .tpl files untouched and report them
```
*Optional Penguin-only fixes:*
```
--penguin-hold-fix        applies the Penguin's nursery MOPP bypass fix (see: wozfix.py)
--penguin-nursery-fix     applies the Penguin beak hold edit fix (see: wozfix.py)
```
### woz_langpkg.py
VERY IMPORTANT. While some data was included with the PC game, all language packages weren't. The missing ones need to be obtained as well from a Wii copy and converted with this script to make the Wii animals load. This script IS NOT included in `wozconvert` as a module.<br />
LEAVE THESE PC PACKAGES UNTOUCHED: **LanguageAchievement.pkg, LanguageCommon.pkg, LanguageStartup.pkg**
```
    python woz_langpkg.py info Language.pkg
    python woz_langpkg.py extract Language.pkg OutFolder
    python woz_langpkg.py convert Language.pkg Language_new.pkg  [options]
```
*Options:*
```
--to pc | wii     only used with ``convert`` to choose Little Endian or Big Endian
```
### wozpkg.py
Can extract and repack the .pkg animal files. Works with either Wii or PC packages, both for extraction and repackaging them back to be byte-exact. A ``_manifest.json`` file is generated in the output folder, which lists the content of the folder structure.
```
    python wozpkg.py list Animal.pkg
    python wozpkg.py extract Animal.pkg OutFolder
    python wozpkg.py repack OutFolder Animal_new.pkg  [options]
```
*Options:*
```
--endian le | be    repackages files to Little Endian (le) or Big Endian (be). If no option, it defaults to le for PC
--level N           optional: changes the compression level to be used, default is 6
```
### wozhkx.py
No options. Better implemented as a module to ``wozconvert.py``. <br />
Files it cannot convert (packed/quantized prop and habitat vertex formats) are reported and skipped - never half-converted.
```
    python wozhkx.py In.hkx Out.hkx          converts one file
    python wozhkx.py WiiFolder PCFolder      converts every .hkx inside, same relative paths
```
### woztpl.py
Converts GameCube/Wii TPL textures to TGA (32-bit BGRA) or DDS (uncompressed 32-bit RGBA). Supports common TPL formats: I4, I8, IA4, IA8, RGB565, RGB5A3, RGBA8, C4, C8, C14X2 and CMPR. Indexed formats require a valid palette in the TPL. Multiple-image TPLs are written as name_0, name_1, ...
```
    python woztpl.py texture.tpl  [options]
    python woztpl.py WiiFolder  [options]
```
*Options:*
```
--out OutFolder    output converted files to the defined folder. Default is "converted_textures" in the same dir. as the files
--format dds | tga | both    converts only to DDS, only to TGA, or both files at the same time. Otherwise defaults to TGA
--info            list dimensions and formats without converting
--recursive       recursively scan input directory (default behavior for directories)
--tga-raw         writes the layers uncompressed, which fixed and error where the animals' textures didn't work
--tga-legacy      restores the old output for comparison, which was used before the error was fixed currently
```
### wozdsc.py
Used to convert these data files from Big-Endian (Wii) to Little-Endian (PC): binary .dsc/.pmp/.xml property files, and .rlet images.<br />
Map entries are written in the PC engine's order, learned from PC reference files.
Better implemented as a module in `wozconvert`, it converts involved files automatically.

*Commands:*
```
src               point to a .dsc/.pmp/.xml file, or a folder to be converted (every BFBINARY .dsc/.pmp/.xml inside is converted; text files are left alone)
dst               output file or folder (may equal src to convert in place)
```
*Options:*
```
--ref file.pkg                  PC reference: PC .pkg files and/or folders of PC .dsc files (more animals = better coverage)
--table woz_order_table.json    load/save the learned order table (JSON); loaded if it exists, otherwise written after building from --ref
```
### wozfix.py
Optional fixes for the Penguins, OFF BY DEFAULT. Won't touch any other files, either by skipping or refusing to modify. Includes:
- A fix that bypasses the MOPP trees for the Penguin's nursery (NurseryPool.pkg/environments/nurserypool/model/nurserypool.hkx), which either don't convert well or break on PC for this specific exhibit. A real fix would probably need someone with more experience in Havok Engine.
- An edit to the Penguin's `Mouth_Attach_Point` (PenguinAnimal.pkg/actors/penguinjackass/model/penguinjackass_adult_m.hkx) moved back along the beak by 0.06 model units. Isn't very noticeable but items are held slightly closer to the beak.
```
    python wozfix.py FileIN.hkx FileOUT.hkx [options]
```
*Options:*
```
nursery           applies the Penguin's nursery MOPP bypass fix
hold              applies the Penguin beak hold edit fix
```
*Alternative:*
```
    python wozconvert.py --penguin-hold-fix / --penguin-nursery-fix
```
---------------------------------------------------------------------------------------
## About StartPC.cfg:
The only obstacle left once everything else is converted. VERY IMPORTANT as well. You only need to modify the `StartPC.cfg` in the game's install folder. I haven't touched the one created with the save file inside "My Games" in Documents, but it's not needed.<br />

To activate the missing animals on all zoo's main menu screen, go to <AnimalFamilyManifests> and add these at the end of the list:<br/>
```
	<Manifest>Config/Animal/Bear_AnimalFamilyManifest.pmp</Manifest>
	<Manifest>Config/Animal/Crocodile_AnimalFamilyManifest.pmp</Manifest>
	<Manifest>Config/Animal/Elephant_AnimalFamilyManifest.pmp</Manifest>
	<Manifest>Config/Animal/Gazelle_AnimalFamilyManifest.pmp</Manifest>
	<Manifest>Config/Animal/Penguin_AnimalFamilyManifest.pmp</Manifest>
```
Then, change this line to bring back the original intro movie with all animals:<br/>
```  <IntroMovie filename="data/00_Retail/BinkMovies/Intro_640.bik" />```
Default is `data/00_Retail/BinkMovies/Intro_PC1_640.bik`.<br/>
Pretty curious how Intro_PC2_640.bik included the other animals only...

Or to disable the intro movie altogether, change fastIntro to "true":<br/>
```  <Debug fastIntro="true" disableAppFocus="false" />```
You can also set *disableAppFocus* to *"true"* if you play on Windowed and want the game to keep going when unfocused.

...
I guess you could play with **<SKUs>** if you converted the whole Wii folder and pointed `StartPC.cfg` out to it, along modifying other things, but I haven't tried this.

---------------------------------------------------------------------------------------
## FAQ:
- *What kind of copy do I need?* <br/>
Any. I can confirm that this works with the 2009 USA retail release and so it should work with any other region releases. The converted files haven't been tested with the Steam version, as I don't have it, yet it should work too!

- *What about the sound / audio files?* <br/>
At least on the retail release, they've been there all this time on all copies since 2009, and they do work as-is!

- *There are some lines that enable debugging but nothing happens!* <br/>
Sadly, it seems that all the code that would've made them work got completely removed when the game was released. There are some traces in WozRetail.exe, pointing that it did have an included debugger / crash handler, and also the logger was seemingly called *BFlog*.<br/>
The game's original demo is an older version than the retail game BUT it doesn't have any other traces or leftovers that can restore this content in any form. They knew very well what they were doing.
...But you're still welcome to try seeing if I'm wrong!

- *What does PatchCFG do then?* <br/>
Not much. I always believed it would be used to implement the missing animals IF they had been released, and now I think I was kinda right. It edits StartPC.cfg but apparently only on request. It was possibly shipped with the game so that one day, when the pressumed expansion released, they called it up with a command to edit the StartPC.cfg and add the other exhibits and the OG intro (which I did myself on the mod I uploaded).

- *Hey, you used AI! YOU SHOULD BE ASHAMED, IT'S BAD!* <br/>
Yes, I'm aware. Yes, I know it's bad / corporate evil. Yes, it is horribly ironic that these scripts for an animal game could've contributed to global warming and destruction of habitats. And I deeply disagree with things going this way.<br/>
<br/>
That's why I beg of you as well to **PLEASE DONATE**. Donate to your local shelter or animal welfare program in the area even if you can't send funds to the more well-known organizations. Animals can't ask for help, they just can run from all that's happening around them.

---------------------------------------------------------------------------------------
## Closing:
While I would have liked to make something better or with a GUI or easier to use, I really hope this encourages people to come back to this beautiful game, even if it's mostly for children or a petting zoo, compared to the more complex Zoo Tycoon series.

I'm sure there's lot of room for optimization and that someone with much more time and skills will some day even manage to import custom models, more patterns, or toys. For now, these tools work with converting both Wii and PC files back and forth, and some light modding. 

Now, the biggest feat after this has to be porting the NDS Canines + enclosure to PC.
Something seemingly impossible but who knows!
