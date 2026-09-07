/**
 * Chinook Database tool nodes — the canvas half.
 *
 * These declare the node types (label, ports, card); the tools that actually
 * run live in `workflows/chinook-assistant/tools/chinook.py` and read the real
 * `Chinook_Sqlite.sqlite` over a `mode=ro` connection.
 *
 * **The schema is the database's, and nothing here keeps a copy of it.** This
 * file used to carry a `CHINOOK_SCHEMA` constant restating every table's
 * columns and types so the browser-preview executors could answer offline.
 * That was duplicated knowledge whose source of truth is a `.sqlite` file, and
 * duplicated knowledge with no drift guard becomes wrong quietly — the worst
 * way for a *schema* to be wrong, because a plausible-looking column name
 * produces SQL that parses and answers the wrong question. So the two
 * schema-shaped tools now refuse in the browser preview and name where the
 * answer lives, the same honest-refusal pattern a dozen other executors here
 * already use. The reader is not left worse off: the card
 * (`view/nodes/SqlSchemaBody`) shows the real tables and their columns, read
 * from the file through `GET /api/workflows/{slug}/sql-schema`.
 *
 * `SAMPLE_DATA` below is a different thing and stays: it fabricates *rows*,
 * not structure, for a preview that is clearly labelled a simulation, and no
 * schema decision is taken from it.
 */

import { Ok, Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { ExecutionContext, INodeExecutor, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import { ToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

/* ================================================================== *
 * Get Table Schema
 * ================================================================== */

/**
 * Returns the schema for whichever table the **agent** asks about.
 *
 * **There is deliberately no `Table` control here.** There used to be: a
 * select of eleven hardcoded names defaulting to `Artist`. It configured
 * nothing — the tool that actually runs
 * (`workflows/chinook-assistant/tools/chinook.py`) takes `table` as a model
 * argument and declares no `configure()`, so node data never reached it — and
 * it told every reader something false, that this node fetches Artist's
 * schema. The agent sees every table and picks; the card says so by showing
 * the real tables (`SqlSchemaBody`), read from the database itself.
 *
 * A document saved before this change still carries `tableName` in its data.
 * That is harmless and stays harmless: node data is a bag, unknown keys are
 * ignored on load, no field renders one, and the compiler never read it even
 * when the control existed. Nothing to migrate — removing the control changed
 * no compiled behaviour in either direction, which is why the schema version
 * does not move (`backend/openstategraph/schema.py` bumps for changes that
 * alter what a document *compiles to*).
 */
export const getTableSchemaNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.chinook-get-schema',
    scope: 'workflow',
    label: 'Get Table Schema',
    description:
      'Retrieves the schema (columns, types and foreign keys) of whichever Chinook table the agent asks about.',
    iconId: 'node-database',
    accent: 'blue',
    keywords: ['database', 'schema', 'table', 'chinook', 'sql'],
    defaultSize: { width: 280, height: 160 },
    fields: [],
  },
  ToolNodeModel,
);

/**
 * The one message both schema tools give in the browser preview.
 *
 * Named once because saying it twice, differently, is how two answers to the
 * same question start to disagree.
 */
const NO_LOCAL_DATABASE =
  'The Chinook schema comes from the database file itself (workflows/chinook-assistant/data/Chinook_Sqlite.sqlite), which the browser cannot open. Run this workflow through the runtime — the agent gets the real schema there, and this node’s card shows the same tables.';

const getTableSchemaTool: IToolExecutor = {
  describeTool(): ToolSpec {
    return {
      name: 'get_table_schema',
      description:
        'Returns the schema (column names, types and foreign keys) for a specific table in the Chinook database. Use this to understand the structure of a table before writing queries.',
      parameters: {
        type: 'object',
        properties: {
          tableName: {
            type: 'string',
            description: 'The name of the table to get schema for',
          },
        },
        required: ['tableName'],
        additionalProperties: false,
      },
    };
  },

  async invokeTool(): Promise<Result<string, string>> {
    return Err(NO_LOCAL_DATABASE);
  },
};

export const getTableSchemaExecutor: INodeExecutor = createToolExecutor(
  getTableSchemaNode.id,
  getTableSchemaTool,
);

/* ================================================================== *
 * Get All Tables Info
 * ================================================================== */

/**
 * Returns a list of all tables in the Chinook database.
 */
export const getAllTablesNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.chinook-get-all-tables',
    scope: 'workflow',
    label: 'List All Tables',
    description: 'Returns every table in the Chinook database, with row counts.',
    iconId: 'node-database',
    accent: 'blue',
    keywords: ['database', 'tables', 'chinook', 'sql', 'list'],
    defaultSize: { width: 280, height: 140 },
    fields: [],
  },
  ToolNodeModel,
);

const getAllTablesTool: IToolExecutor = {
  describeTool(): ToolSpec {
    return {
      name: 'get_all_tables',
      description:
        'Returns a complete list of all tables in the Chinook database. Use this first to understand what data is available.',
      parameters: {
        type: 'object',
        properties: {},
        additionalProperties: false,
      },
    };
  },

  async invokeTool(): Promise<Result<string, string>> {
    return Err(NO_LOCAL_DATABASE);
  },
};

export const getAllTablesExecutor: INodeExecutor = createToolExecutor(
  getAllTablesNode.id,
  getAllTablesTool,
);

/* ================================================================== *
 * Execute SQL Query
 * ================================================================== */

export class ExecuteSqlNodeModel extends ToolNodeModel {
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
    scope: 'workflow',
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
