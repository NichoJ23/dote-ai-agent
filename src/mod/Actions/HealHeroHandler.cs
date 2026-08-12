using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles HEAL_HERO command: heals a hero (costs food).
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to heal
    /// </summary>
    public class HealHeroHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "HEAL_HERO"; } }

        public HealHeroHandler(DungeonHook dungeonHook)
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

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            Hero hero = FindHeroByName(heroName);

            // Heal() checks: alive, not full HP, has food, not in strategy phase with regen
            bool success = hero.Heal();

            if (!success)
                return ActionResult.Fail("Heal failed for " + heroName + " (full HP, dead, insufficient food, or strategy phase regen active)");

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["hp"] = hero.HealthCpnt.GetHealth();
            metadata["max_hp"] = hero.HealthCpnt.GetMaxHealth();

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
