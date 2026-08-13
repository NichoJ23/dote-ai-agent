using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles PLUG_CRYSTAL_EXIT command: orders the crystal carrier to plug the crystal
    /// into the exit room's crystal slot, triggering floor completion.
    ///
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero carrying the crystal
    /// </summary>
    public class PlugCrystalExitHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "PLUG_CRYSTAL_EXIT"; } }

        public PlugCrystalExitHandler(DungeonHook dungeonHook)
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

            if (!hero.HasCrystal)
                return "Hero is not carrying the crystal: " + heroName;

            if (!hero.IsUsable)
                return "Hero is not usable: " + heroName;

            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            if (dungeon == null)
                return "Dungeon not available";

            Room exitRoom = dungeon.ExitRoom;
            if (exitRoom == null)
                return "Exit room not found";

            // Hero must be in the exit room
            if (hero.RoomElement.ParentRoom != exitRoom)
                return "Hero is not in the exit room";

            // Exit room must have a free crystal slot
            CrystalModuleSlot slot = exitRoom.GetFreeCrystalModuleSlot(true);
            if (slot == null)
                return "No free crystal slot in exit room";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            Hero hero = FindHeroByName(heroName);
            Dungeon dungeon = SingletonManager.Get<Dungeon>(false);
            Room exitRoom = dungeon.ExitRoom;

            CrystalModuleSlot slot = exitRoom.GetFreeCrystalModuleSlot(true);
            hero.MoveToCrystalSlot(slot);

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;

            Plugin.Log.LogInfo("PlugCrystalExit: Crystal being plugged into exit slot by " + heroName);
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
