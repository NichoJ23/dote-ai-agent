using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Hooks;
using DotEAgent.Models;

namespace DotEAgent.Actions
{
    /// <summary>
    /// Handles DISMISS_HERO command: dismisses a recruited hero from the party.
    /// The hero must be alive, recruited, not carrying the crystal, and the team must have > 1 hero.
    /// Dismissing refunds food based on hero level (level^2 + DismissingFoodCoef).
    /// 
    /// Parameters:
    ///   hero_name (string, required) - Name of the hero to dismiss
    /// </summary>
    public class DismissHeroHandler : IActionHandler
    {
        private readonly DungeonHook dungeonHook;

        public string CommandType { get { return "DISMISS_HERO"; } }

        public DismissHeroHandler(DungeonHook dungeonHook)
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

            if (!hero.IsRecruited)
                return "Hero is not recruited: " + heroName;

            if (!hero.HealthCpnt.IsAlive())
                return "Cannot dismiss a dead hero: " + heroName;

            if (hero.HasCrystal)
                return "Cannot dismiss a hero carrying the crystal";

            // Must have more than 1 hero
            int totalHeroes = Hero.LocalPlayerActiveRecruitedHeroes != null
                ? Hero.LocalPlayerActiveRecruitedHeroes.Count
                : 0;
            if (totalHeroes <= 1)
                return "Cannot dismiss last remaining hero";

            return null;
        }

        public ActionResult Execute(ActionCommand command)
        {
            string heroName = command.GetString("hero_name");
            Hero hero = FindHeroByName(heroName);

            int roomIndex = dungeonHook.GetRoomIndex(hero.RoomElement.ParentRoom);

            // Dismiss the hero (game handles food refund internally)
            hero.Dismiss();

            var metadata = new Dictionary<string, object>();
            metadata["hero_name"] = heroName;
            metadata["dismissed_from_room"] = roomIndex;

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
