using System.Collections.Generic;

namespace DotEAgent.Models
{
    public class HeroStateData
    {
        public string Name;
        public string Faction;            // "Other", "Guard", "Prisoner", "Native"
        public int RoomIndex;
        public float Hp;
        public float MaxHp;
        public int Level;
        public bool HasCrystal;
        public bool IsOperating;
        public string OperatingModuleName;
        public bool IsGatheringItem;      // Currently in item pickup animation (do NOT move hero)
        public bool IsRecruitable;
        public bool IsRecruited;
        public bool IsUsable;             // False when hero is in animation, dead, respawning, etc.

        // Combat stats (computed from SimulationProperties via equipment, level, passives)
        public float Attack;              // AttackPower
        public float Defense;             // Defense
        public float Speed;               // MoveSpeed
        public float Wit;                 // Wit (module operation effectiveness)
        public float AttackCooldown;      // Time between attacks

        public List<ActiveSkillData> ActiveSkills;
        public List<PassiveSkillData> PassiveSkills;
        public List<EquipmentSlotData> Equipment;
    }

    public class ActiveSkillData
    {
        public string Name;
        public int CooldownTurns;         // Total cooldown duration
        public int RemainingCooldown;     // Turns until ready (0 = ready)
        public bool IsActivated;          // Currently active
    }

    public class PassiveSkillData
    {
        public string Name;
    }

    public class EquipmentSlotData
    {
        public string SlotCategory;       // e.g., "Weapon", "Armor", "Accessory"
        public string ItemName;           // null if slot empty
    }
}
