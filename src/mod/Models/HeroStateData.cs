using System.Collections.Generic;

namespace DotEAgent.Models
{
    public class HeroStateData
    {
        public string Name;
        public string Faction;            // "Other", "Guard", "Prisoner", "Native"
        public string WeaponClass;        // Hero's innate attack type (e.g., "Melee", "Ranged") from HeroConfig.AttackType
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
        public float LevelUpCost;         // Food cost to reach next level (0 if max level)

        public List<ActiveSkillData> ActiveSkills;
        public List<PassiveSkillData> PassiveSkills;
        public List<EquipmentSlotData> Equipment;

        /// <summary>
        /// Complete skill tree for this hero: all skills that can be unlocked at any level,
        /// including those not yet unlocked. Helps the agent decide leveling priority.
        /// </summary>
        public List<SkillTreeEntry> SkillTree;
    }

    public class ActiveSkillData
    {
        public string Name;
        public int SkillLevel;            // Skill tier (from SkillConfig.Level, e.g., 1, 2, 3)
        public int UnlockLevel;           // Hero level at which this skill unlocks (0 if already present at start)
        public int CooldownTurns;         // Total cooldown duration
        public int RemainingCooldown;     // Turns until ready (0 = ready)
        public bool IsActivated;          // Currently active
    }

    public class PassiveSkillData
    {
        public string Name;
        public int SkillLevel;            // Skill tier (from SkillConfig.Level)
        public int UnlockLevel;           // Hero level at which this passive unlocks (0 if already present at start)
    }

    public class EquipmentSlotData
    {
        public string SlotCategory;       // e.g., "Weapon", "Armor", "Accessory"
        public string ItemName;           // null if slot empty
        public string WeaponType;         // Weapon sub-type from ItemHeroConfig.CategoryParameters.TypeName (null if not a weapon or empty)
        public string AttackType;         // Attack type from ItemHeroConfig.AttackTypeConfigName (null if not a weapon or empty)
    }

    /// <summary>
    /// An entry in the hero's full skill tree showing what they can unlock and at what level.
    /// </summary>
    public class SkillTreeEntry
    {
        public string SkillName;          // Skill config name (e.g., "Skill_A_MaxOKane_LVL1")
        public string BaseName;           // Base name without level suffix (e.g., "Skill_A_MaxOKane")
        public bool IsActive;             // True = active skill, false = passive skill
        public int SkillLevel;            // Tier of the skill (from SkillConfig.Level)
        public int UnlockHeroLevel;       // The hero level at which this becomes available
        public bool IsUnlocked;           // Whether the hero has reached this level already
    }
}
