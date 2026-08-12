using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles PICK_UP_CRYSTAL command: sends a hero to unplug and carry the crystal.
    /// Hero must be in the crystal room (start room).
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to carry the crystal
    /// </summary>
    public class PickUpCrystalHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "PICK_UP_CRYSTAL"; } }

        public PickUpCrystalHandler(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public string ValidatePreconditions(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            if (string.IsNullOrEmpty(heroName))
                return "Missing required parameter: hero_name";

            Hero hero = FindHeroByName(heroName);
            if (hero == null)
                return "Hero not found: " + heroName;

            if (!hero.IsUsable)
                return "Hero is not usable: " + heroName;

            if (hero.HasCrystal)
                return "Hero is already carrying the crystal";

            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return "Dungeon not available";

            // Crystal must be plugged in (not already being carried)
            if (dungeon.CurrentCrystalState != CrystalState.Plugged)
                return "Crystal is not plugged in (state: " + dungeon.CurrentCrystalState.ToString() + ")";

            // Hero must be in the crystal room (start room)
            Room crystalRoom = dungeon.StartRoom;
            Room heroRoom = hero.RoomElement.ParentRoom;
            if (heroRoom != crystalRoom)
            {
                int heroRoomIndex = dungeonHook.GetRoomIndex(heroRoom);
                int crystalRoomIndex = dungeonHook.GetRoomIndex(crystalRoom);
                return "Hero " + heroName + " is in room " + heroRoomIndex
                    + ", not in crystal room " + crystalRoomIndex;
            }

            // Verify crystal module exists
            if (crystalRoom.MajorModule == null || !crystalRoom.MajorModule.IsCrystal)
                return "No crystal module found in start room";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");

            Hero hero = FindHeroByName(heroName);
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            MajorModule crystalModule = dungeon.StartRoom.MajorModule;

            // MoveToCrystal moves the hero to the crystal and unplugs it on arrival
            hero.MoveToCrystal(crystalModule);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;

            return ActionResult.Ok(metadata);
        }

        private Hero FindHeroByName(string name)
        {
            List<Hero> heroes = Hero.LocalPlayerActiveRecruitedHeroes;
            if (heroes == null)
                return null;

            for (int i = 0; i < heroes.Count; i++)
            {
                Hero hero = heroes[i];
                if (hero == null)
                    continue;

                string heroName = hero.LocalizedName;
                if (string.IsNullOrEmpty(heroName) && hero.Config != null)
                    heroName = hero.Config.Name.ToString();

                if (heroName == name)
                    return hero;
            }
            return null;
        }
    }
}
