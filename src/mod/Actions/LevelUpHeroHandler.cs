using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles LEVEL_UP_HERO command: levels up a hero (costs food).
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to level up
    /// </summary>
    public class LevelUpHeroHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "LEVEL_UP_HERO"; } }

        public LevelUpHeroHandler(DungeonHook dungeonHook)
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

            int levelBefore = hero.Level;

            // LevelUp(bool playFeedback, bool consumeFood)
            // Game internally checks CanLevelUp (max level, food cost)
            hero.LevelUp(true, true);

            if (hero.Level <= levelBefore)
                return ActionResult.Fail("Level up failed for " + heroName + " (insufficient food or max level reached)");

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["new_level"] = hero.Level;

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
