import mongoose from 'mongoose';
import { MongoMemoryServer } from 'mongodb-memory-server';
import type { IAgentCategory } from '..';
import { createAgentCategoryMethods } from './agentCategory';
import { createModels } from '../models';

jest.mock('~/config/winston', () => ({
  error: jest.fn(),
  warn: jest.fn(),
  info: jest.fn(),
  debug: jest.fn(),
}));

let mongoServer: MongoMemoryServer;
let AgentCategory: mongoose.Model<IAgentCategory>;
let methods: ReturnType<typeof createAgentCategoryMethods>;

beforeAll(async () => {
  mongoServer = await MongoMemoryServer.create();
  await mongoose.connect(mongoServer.getUri());
  createModels(mongoose);
  AgentCategory = mongoose.models.AgentCategory as mongoose.Model<IAgentCategory>;
  methods = createAgentCategoryMethods(mongoose);
});

afterAll(async () => {
  await mongoose.disconnect();
  await mongoServer.stop();
});

describe('ensureDefaultCategories', () => {
  it('seeds the animal care category after the stock ones and stays idempotent', async () => {
    await methods.ensureDefaultCategories();
    await methods.ensureDefaultCategories();

    const categories = await methods.getAllCategories();
    expect(categories.map((category) => category.value)).toEqual([
      'general',
      'hr',
      'rd',
      'finance',
      'it',
      'sales',
      'aftersales',
      'animal_care',
    ]);
    const animalCare = await AgentCategory.findOne({ value: 'animal_care' }).lean();
    expect(animalCare?.label).toBe('com_agents_category_animal_care');
    expect(animalCare?.description).toBe('com_agents_category_animal_care_description');
  });
});
