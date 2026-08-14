namespace DotEAgent.Models
{
    /// <summary>
    /// A buildable (unlocked) module blueprint with cost and category info.
    /// </summary>
    public class BuildableBlueprintData
    {
        public string Name;              // Blueprint name (e.g., "MajorModule_Major0002_LVL1")
        public string ModuleName;        // Module config name (e.g., "Major0002")
        public string Category;          // "MajorModule", "MinorModule_Support", "MinorModule_Offense", "MinorModule_Debuff"
        public int Level;                // Module level tier
        public float IndustryCost;       // Current industry cost to build (includes increment)
    }
}
