/**
 * Chinook Database tool nodes.
 *
 * Provides tools for:
 * - Getting table schemas
 * - Getting columns by table
 * - Executing SQL queries
 *
 * The Chinook database is a sample music store database with tables for:
 * - Artist, Album, Track, Genre
 * - Customer, Employee, Invoice, InvoiceLine, Playlist, PlaylistTrack, MediaType
 */

import { Ok, Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { ExecutionContext, INodeExecutor, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import { AbstractToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

/* ================================================================== *
 * Get Table Schema
 * ================================================================== */

const FIELD_TABLE_NAME = 'tableName';

export class GetTableSchemaNodeModel extends AbstractToolNodeModel {
  get tableName(): string {
    return this.getText(FIELD_TABLE_NAME).trim();
  }
}

/**
 * Returns the schema (columns and types) for a specific table.
 */
export const getTableSchemaNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.chinook-get-schema',
    label: 'Get Table Schema',
    description: 'Retrieves the schema (column names and types) for a Chinook database table.',
    iconId: 'node-database',
    accent: 'blue',
    keywords: ['database', 'schema', 'table', 'chinook', 'sql'],
    defaultSize: { width: 280, height: 160 },
    fields: [
      {
        kind: 'select',
        key: FIELD_TABLE_NAME,
        label: 'Table',
        options: () => [
          { value: 'Artist', label: 'Artist' },
          { value: 'Album', label: 'Album' },
          { value: 'Track', label: 'Track' },
          { value: 'Genre', label: 'Genre' },
          { value: 'MediaType', label: 'MediaType' },
          { value: 'Playlist', label: 'Playlist' },
          { value: 'PlaylistTrack', label: 'PlaylistTrack' },
          { value: 'Customer', label: 'Customer' },
          { value: 'Employee', label: 'Employee' },
          { value: 'Invoice', label: 'Invoice' },
          { value: 'InvoiceLine', label: 'InvoiceLine' },
        ],
        defaultValue: 'Artist',
      },
    ],
  },
  GetTableSchemaNodeModel,
);

// Chinook database schema
const CHINOOK_SCHEMA: Record<string, { columns: { name: string; type: string }[] }> = {
  Artist: {
    columns: [
      { name: 'ArtistId', type: 'INTEGER PRIMARY KEY' },
      { name: 'Name', type: 'NVARCHAR(120)' },
    ],
  },
  Album: {
    columns: [
      { name: 'AlbumId', type: 'INTEGER PRIMARY KEY' },
      { name: 'Title', type: 'NVARCHAR(160)' },
      { name: 'ArtistId', type: 'INTEGER FOREIGN KEY' },
    ],
  },
  Track: {
    columns: [
      { name: 'TrackId', type: 'INTEGER PRIMARY KEY' },
      { name: 'Name', type: 'NVARCHAR(200)' },
      { name: 'AlbumId', type: 'INTEGER FOREIGN KEY' },
      { name: 'MediaTypeId', type: 'INTEGER FOREIGN KEY' },
      { name: 'GenreId', type: 'INTEGER FOREIGN KEY' },
      { name: 'Composer', type: 'NVARCHAR(220)' },
      { name: 'Milliseconds', type: 'INTEGER' },
      { name: 'Bytes', type: 'INTEGER' },
      { name: 'UnitPrice', type: 'NUMERIC(10,2)' },
    ],
  },
  Genre: {
    columns: [
      { name: 'GenreId', type: 'INTEGER PRIMARY KEY' },
      { name: 'Name', type: 'NVARCHAR(38)' },
    ],
  },
  MediaType: {
    columns: [
      { name: 'MediaTypeId', type: 'INTEGER PRIMARY KEY' },
      { name: 'Name', type: 'NVARCHAR(50)' },
    ],
  },
  Playlist: {
    columns: [
      { name: 'PlaylistId', type: 'INTEGER PRIMARY KEY' },
      { name: 'Name', type: 'NVARCHAR(120)' },
    ],
  },
  PlaylistTrack: {
    columns: [
      { name: 'PlaylistId', type: 'INTEGER PRIMARY KEY' },
      { name: 'TrackId', type: 'INTEGER PRIMARY KEY' },
    ],
  },
  Customer: {
    columns: [
      { name: 'CustomerId', type: 'INTEGER PRIMARY KEY' },
      { name: 'FirstName', type: 'NVARCHAR(40)' },
      { name: 'LastName', type: 'NVARCHAR(20)' },
      { name: 'Company', type: 'NVARCHAR(80)' },
      { name: 'Address', type: 'NVARCHAR(70)' },
      { name: 'City', type: 'NVARCHAR(40)' },
      { name: 'State', type: 'NVARCHAR(40)' },
      { name: 'Country', type: 'NVARCHAR(40)' },
      { name: 'PostalCode', type: 'NVARCHAR(10)' },
      { name: 'Phone', type: 'NVARCHAR(24)' },
      { name: 'Fax', type: 'NVARCHAR(24)' },
      { name: 'Email', type: 'NVARCHAR(60)' },
      { name: 'SupportRepId', type: 'INTEGER FOREIGN KEY' },
    ],
  },
  Employee: {
    columns: [
      { name: 'EmployeeId', type: 'INTEGER PRIMARY KEY' },
      { name: 'LastName', type: 'NVARCHAR(20)' },
      { name: 'FirstName', type: 'NVARCHAR(20)' },
      { name: 'Title', type: 'NVARCHAR(30)' },
      { name: 'ReportsTo', type: 'INTEGER FOREIGN KEY' },
      { name: 'BirthDate', type: 'DATETIME' },
      { name: 'HireDate', type: 'DATETIME' },
      { name: 'Address', type: 'NVARCHAR(70)' },
      { name: 'City', type: 'NVARCHAR(40)' },
      { name: 'State', type: 'NVARCHAR(40)' },
      { name: 'Country', type: 'NVARCHAR(40)' },
      { name: 'PostalCode', type: 'NVARCHAR(10)' },
      { name: 'Phone', type: 'NVARCHAR(24)' },
      { name: 'Fax', type: 'NVARCHAR(24)' },
      { name: 'Email', type: 'NVARCHAR(60)' },
    ],
  },
  Invoice: {
    columns: [
      { name: 'InvoiceId', type: 'INTEGER PRIMARY KEY' },
      { name: 'CustomerId', type: 'INTEGER FOREIGN KEY' },
      { name: 'InvoiceDate', type: 'DATETIME' },
      { name: 'BillingAddress', type: 'NVARCHAR(70)' },
      { name: 'BillingCity', type: 'NVARCHAR(40)' },
      { name: 'BillingState', type: 'NVARCHAR(40)' },
      { name: 'BillingCountry', type: 'NVARCHAR(40)' },
      { name: 'BillingPostalCode', type: 'NVARCHAR(10)' },
      { name: 'Total', type: 'NUMERIC(10,2)' },
    ],
  },
  InvoiceLine: {
    columns: [
      { name: 'InvoiceLineId', type: 'INTEGER PRIMARY KEY' },
      { name: 'InvoiceId', type: 'INTEGER FOREIGN KEY' },
      { name: 'TrackId', type: 'INTEGER FOREIGN KEY' },
      { name: 'UnitPrice', type: 'NUMERIC(10,2)' },
      { name: 'Quantity', type: 'INTEGER' },
    ],
  },
};

const getTableSchemaTool: IToolExecutor = {
  describeTool(node: AbstractNodeModel): ToolSpec {
    const tool = node as GetTableSchemaNodeModel;
    return {
      name: 'get_table_schema',
      description:
        'Returns the schema (column names and types) for a specific table in the Chinook database. Use this to understand the structure of a table before writing queries.',
      parameters: {
        type: 'object',
        properties: {
          tableName: {
            type: 'string',
            description: 'The name of the table to get schema for',
            default: tool.tableName,
          },
        },
        required: ['tableName'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    const tool = node as GetTableSchemaNodeModel;
    const tableName =
      (typeof args['tableName'] === 'string' && args['tableName'].trim()) || tool.tableName;

    const schema = CHINOOK_SCHEMA[tableName];
    if (!schema) {
      return Err(
        `Unknown table: ${tableName}. Available tables: ${Object.keys(CHINOOK_SCHEMA).join(', ')}`,
      );
    }

    ctx.log(`Retrieved schema for table: ${tableName}`);
    return Ok(
      JSON.stringify(
        {
          tableName,
          columns: schema.columns,
        },
        null,
        2,
      ),
    );
  },
};

export const getTableSchemaExecutor: INodeExecutor = createToolExecutor(
  getTableSchemaNode.id,
  getTableSchemaTool,
);

/* ================================================================== *
 * Get All Tables Info
 * ================================================================== */

export class GetAllTablesNodeModel extends AbstractToolNodeModel {}

/**
 * Returns a list of all tables in the Chinook database with brief descriptions.
 */
export const getAllTablesNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.chinook-get-all-tables',
    label: 'List All Tables',
    description: 'Returns a list of all tables in the Chinook database with descriptions.',
    iconId: 'node-database',
    accent: 'blue',
    keywords: ['database', 'tables', 'chinook', 'sql', 'list'],
    defaultSize: { width: 280, height: 140 },
    fields: [],
  },
  GetAllTablesNodeModel,
);

const TABLE_DESCRIPTIONS: Record<string, string> = {
  Artist: 'Music artists (bands, singers)',
  Album: 'Music albums, linked to artists',
  Track: 'Individual songs/tracks with duration and pricing',
  Genre: 'Music genres (Rock, Jazz, etc.)',
  MediaType: 'Audio/video formats (MP3, AAC, etc.)',
  Playlist: 'User-created playlists',
  PlaylistTrack: 'Junction table linking playlists to tracks',
  Customer: 'Store customers with contact info',
  Employee: 'Store employees, some support customers',
  Invoice: 'Customer purchase invoices',
  InvoiceLine: 'Individual items on invoices',
};

const getAllTablesTool: IToolExecutor = {
  describeTool(): ToolSpec {
    return {
      name: 'get_all_tables',
      description:
        'Returns a complete list of all tables in the Chinook database with their descriptions. Use this first to understand what data is available.',
      parameters: {
        type: 'object',
        properties: {},
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    _node: AbstractNodeModel,
    _args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    ctx.log('Retrieved list of all tables');
    return Ok(
      JSON.stringify(
        {
          tables: Object.entries(CHINOOK_SCHEMA).map(([name, schema]) => ({
            name,
            columnCount: schema.columns.length,
            description: TABLE_DESCRIPTIONS[name] || 'No description available',
          })),
        },
        null,
        2,
      ),
    );
  },
};

export const getAllTablesExecutor: INodeExecutor = createToolExecutor(
  getAllTablesNode.id,
  getAllTablesTool,
);

/* ================================================================== *
 * Execute SQL Query
 * ================================================================== */

export class ExecuteSqlNodeModel extends AbstractToolNodeModel {
  get maxRows(): number {
    return this.getNumber('maxRows', 100);
  }
}

/**
 * Executes a SQL query against the Chinook database.
 *
 * Since we don't have a real database connection in the browser,
 * this simulates query execution by parsing common SQL patterns
 * and returning mock data that matches the expected schema.
 */
export const executeSqlNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.chinook-execute-sql',
    label: 'Execute SQL Query',
    description: 'Executes a SQL SELECT query against the Chinook database and returns results.',
    iconId: 'node-database',
    accent: 'green',
    keywords: ['database', 'sql', 'query', 'execute', 'chinook'],
    defaultSize: { width: 320, height: 200 },
    fields: [
      {
        kind: 'slider',
        key: 'maxRows',
        label: 'Max rows',
        min: 10,
        max: 1000,
        step: 10,
        defaultValue: 100,
        format: (value) => `${value}`,
      },
    ],
  },
  ExecuteSqlNodeModel,
);

// Sample data for simulating query results
const SAMPLE_DATA: Record<string, Record<string, unknown>[]> = {
  Artist: [
    { ArtistId: 1, Name: 'AC/DC' },
    { ArtistId: 2, Name: 'Accept' },
    { ArtistId: 3, Name: 'Aerosmith' },
    { ArtistId: 4, Name: 'Alanis Morissette' },
    { ArtistId: 5, Name: 'Alice In Chains' },
  ],
  Album: [
    { AlbumId: 1, Title: 'For Those About To Rock We Salute You', ArtistId: 1 },
    { AlbumId: 2, Title: 'Balls to the Wall', ArtistId: 2 },
    { AlbumId: 3, Title: 'Restless and Wild', ArtistId: 2 },
    { AlbumId: 4, Title: 'Let There Be Rock', ArtistId: 1 },
    { AlbumId: 5, Title: 'Big Ones', ArtistId: 3 },
  ],
  Track: [
    {
      TrackId: 1,
      Name: 'For Those About To Rock (We Salute You)',
      AlbumId: 1,
      Milliseconds: 343719,
      UnitPrice: 0.99,
    },
    { TrackId: 2, Name: 'Balls to the Wall', AlbumId: 2, Milliseconds: 342562, UnitPrice: 0.99 },
    { TrackId: 3, Name: 'Fast As a Shark', AlbumId: 3, Milliseconds: 230619, UnitPrice: 0.99 },
  ],
  Genre: [
    { GenreId: 1, Name: 'Rock' },
    { GenreId: 2, Name: 'Jazz' },
    { GenreId: 3, Name: 'Metal' },
    { GenreId: 4, Name: 'Alternative & Punk' },
    { GenreId: 5, Name: 'Rock And Roll' },
  ],
  Customer: [
    {
      CustomerId: 1,
      FirstName: 'Luís',
      LastName: 'Gonçalves',
      Email: 'luisg@embraer.com.br',
      Country: 'Brazil',
    },
    {
      CustomerId: 2,
      FirstName: 'Leonie',
      LastName: 'Köhler',
      Email: 'leonekohler@surfeu.de',
      Country: 'Germany',
    },
    {
      CustomerId: 3,
      FirstName: 'François',
      LastName: 'Tremblay',
      Email: 'ftremblay@gmail.com',
      Country: 'Canada',
    },
  ],
  Employee: [
    {
      EmployeeId: 1,
      FirstName: 'Andrew',
      LastName: 'Adams',
      Title: 'General Manager',
      Email: 'andrew@chinookcorp.com',
    },
    {
      EmployeeId: 2,
      FirstName: 'Nancy',
      LastName: 'Edwards',
      Title: 'Sales Manager',
      Email: 'nancy@chinookcorp.com',
    },
    {
      EmployeeId: 3,
      FirstName: 'Jane',
      LastName: 'Peacock',
      Title: 'Sales Support Agent',
      Email: 'jane@chinookcorp.com',
    },
  ],
  Invoice: [
    {
      InvoiceId: 1,
      CustomerId: 1,
      InvoiceDate: '2021-01-01',
      Total: 5.94,
      BillingCountry: 'Brazil',
    },
    {
      InvoiceId: 2,
      CustomerId: 2,
      InvoiceDate: '2021-01-02',
      Total: 12.93,
      BillingCountry: 'Germany',
    },
    {
      InvoiceId: 3,
      CustomerId: 3,
      InvoiceDate: '2021-01-03',
      Total: 8.91,
      BillingCountry: 'Canada',
    },
  ],
};

const executeSqlTool: IToolExecutor = {
  describeTool(_node: AbstractNodeModel): ToolSpec {
    return {
      name: 'execute_sql_query',
      description:
        'Executes a SQL SELECT query against the Chinook database. Returns the query results as JSON. Use this to retrieve actual data after understanding the schema.',
      parameters: {
        type: 'object',
        properties: {
          sqlQuery: {
            type: 'string',
            description: 'A valid SQL SELECT query to execute',
          },
        },
        required: ['sqlQuery'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>> {
    const tool = node as ExecuteSqlNodeModel;
    const sqlQuery = typeof args['sqlQuery'] === 'string' ? args['sqlQuery'].trim() : '';
    const maxRows = tool.maxRows || 100;

    if (!sqlQuery) {
      return Err('No SQL query provided');
    }

    // Validate it's a SELECT query
    const normalizedQuery = sqlQuery.toUpperCase();
    if (!normalizedQuery.startsWith('SELECT')) {
      return Err('Only SELECT queries are allowed for safety reasons');
    }

    // Check for dangerous operations
    if (
      normalizedQuery.includes('DELETE') ||
      normalizedQuery.includes('DROP') ||
      normalizedQuery.includes('INSERT') ||
      normalizedQuery.includes('UPDATE')
    ) {
      return Err('Dangerous operations (DELETE, DROP, INSERT, UPDATE) are not allowed');
    }

    // Extract table names from query using simple regex
    const tableMatches = sqlQuery.match(/FROM\s+(\w+)/i);
    if (!tableMatches) {
      return Err('Could not parse FROM clause - please specify a table');
    }

    const tableName = tableMatches[1];
    if (!tableName) {
      return Err('Could not extract table name from query');
    }
    const tableData = SAMPLE_DATA[tableName];

    if (!tableData) {
      return Err(`Unknown table: ${tableName}. Available: ${Object.keys(SAMPLE_DATA).join(', ')}`);
    }

    ctx.log(`Executed SQL query on table: ${tableName}`);

    // Simple simulation: return sample data
    // In a real implementation, this would connect to an actual database
    const results = tableData.slice(0, maxRows);

    return Ok(
      JSON.stringify(
        {
          query: sqlQuery,
          tableName,
          rowCount: results.length,
          columns: Object.keys(results[0] || {}),
          rows: results,
        },
        null,
        2,
      ),
    );
  },
};

export const executeSqlExecutor: INodeExecutor = createToolExecutor(
  executeSqlNode.id,
  executeSqlTool,
);

/* ================================================================== *
 * Export all Chinook nodes
 * ================================================================== */

export const CHINOOK_NODES = [
  { definition: getTableSchemaNode, executor: getTableSchemaExecutor },
  { definition: getAllTablesNode, executor: getAllTablesExecutor },
  { definition: executeSqlNode, executor: executeSqlExecutor },
];
