using System.Collections.Generic;

namespace DotEAgent.Models
{
    public class RecruitableHeroData
    {
        public string Name;
        public string Faction;
        public string WeaponClass;        // Hero's innate attack type from HeroConfig.AttackType
        public int RoomIndex;
        public float Hp;
        public float MaxHp;
        public float RecruitCostFood;
        public List<string> ActiveSkillNames;
        public List<string> PassiveSkillNames;

        /// <summary>
        /// Complete skill tree for this hero: all skills that can be unlocked at any level.
        /// Helps the agent evaluate whether recruiting this hero is worthwhile based on
        /// future ability unlocks vs. current roster.
        /// </summary>
        public List<SkillTreeEntry> SkillTree;
    }
}
