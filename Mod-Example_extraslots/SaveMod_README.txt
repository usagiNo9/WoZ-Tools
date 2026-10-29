------------------------------------------
How to use woz-savemod.py:
------------------------------------------
First, make sure the game is closed, and get your save file from Documents\My Games\World of Zoo. You should see ZooInfo0, ZooInfo1, and ZooInfo2. These are the ones you need, whichever you want to edit. MAKE A BACKUP OF THE FILES BEFORE EDITING THEM.
For reference:
- ZooInfo0 is the yellow Zoo
- ZooInfo1 is the blue Zoo
- ZooInfo2 is the pink Zoo

Once you have identified which one is yours and you've made a backup, open CMD in the tool's folder, and paste or tweak this command:
		  python woz_savemod.py slots ZooInfo0 ZooInfo0_Unlocked --count 6 --all --no-nurseries

This should unlock the 6 slots for ALL animals, regardless of which rank you're on. Remove "_Unlocked" and replace the original.

All Commands:
       show  ZooInfo0                   displays information about the save file's slots
       slots  ZooInfo0 OUTFolder        applies options to the save file + outputs it to a folder
       slots  ZooInfo0 ZooInfo0_new     applies options to the save file + outputs in the same folder
       unlock  ZooInfo0 OUTFolder       used to unlock specific slots + outputs to a folder
       lock  ZooInfo0 OUTFolder         used to re-lock specific slots + outputs to a folder

All Options:
       --count 6                 quantity of slots unlocked; must be at least 2 (slot 1 is always available)
       --all                              applies to all animal exhibits, including nurseries
       --no-nurseries                     if used with --all; excludes nurseries
       --only-nurseries                   if used with --all; applies to nurseries only
       --habitat ExhibitA,ExhibitB        comma separated exhibit id prefixes, e.g. BigCatSavanna,BearForest
       --ids XSlot1,XSlot2                comma separated slot id prefixes, e.g. BigCatSavannaSlot4,BigCatSavannaSlot5
       --tag NAME                         add an underscore and word to the output name, for tagging files

------------------------------------------
  Examples
------------------------------------------
- Unlock more slots ONLY for some exhibits (example: big cats and bear):
		  python woz_savemod.py slots ZooInfo0 ZooInfo0_Unlocked --count 6 --habitat BigCatSavanna,BearForest
- Unlock only slot 4 and 5 of the Big Cats exhibit:
		  python woz_savemod.py unlock ZooInfo0 ZooInfo0_Unlocked --ids BigCatSavannaSlot4,BigCatSavannaSlot5
- Re-locks only slot 4 and 5 of the Big Cats exhibit, leaving the save file back to normal:
		python woz_savemod.py lock ZooInfo0 ZooInfo0_Locked --ids BigCatSavannaSlot4,BigCatSavannaSlot5

------------------------------------------------------------------------------------

This way you can lock ALL extra slots back to normal:
		python woz_savemod.py lock ZooInfo0 ZooInfo0_Locked --ids BigCatSavannaSlot4,BigCatSavannaSlot5,BigCatSavannaSlot6,BearForestSlot4,BearForestSlot5,BearForestSlot6,CrocodileCoastalSlot4,CrocodileCoastalSlot5,CrocodileCoastalSlot6,ElephantGrasslandSlot4,ElephantGrasslandSlot5,ElephantGrasslandSlot6,GiraffeSavannaSlot4,GiraffeSavannaSlot5,GiraffeSavannaSlot6,PandaForestSlot4,PandaForestSlot5,PandaForestSlot6,AntelopeSavannaSlot5,AntelopeSavannaSlot6,HorseSavannaSlot5,HorseSavannaSlot6,KoalaForestSlot5,KoalaForestSlot6,PenguinPoolSlot5,PenguinPoolSlot6,SmallMonkeyJungleSlot5,SmallMonkeyJungleSlot6

All adult animal's exhibit names:
AntelopeSavanna,BearForest,BigCatSavanna,CrocodileCoastal,ElephantGrassland,GiraffeSavanna,HorseSavanna,KoalaForest,PandaForest,PenguinPool,SmallMonkeyJungle

All baby animal's nurseries names:
AntelopeNursery,NurseryCrocodile,NurseryKoala,NurseryPaddockElephant,NurseryPaddockGiraffe,NurseryPaddockHorse,NurseryPlaypenBear,NurseryPlaypenBigCat,NurseryPlaypenPanda,NurseryPlaypenPenguin,NurserySmallMonkey
