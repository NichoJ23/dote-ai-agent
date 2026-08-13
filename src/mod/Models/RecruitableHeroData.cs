using System.Collections.Generic;

namespace DotEAgent.Models
{
    public class RecruitableHeroData
    {
        public string Name;
        public string Faction;
        public int RoomIndex;
        public float Hp;
        public float MaxHp;
        public float RecruitCostFood;
        public List<string> PassiveSkillNames;
    }
}
